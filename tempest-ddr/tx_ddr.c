/*
 * tx_ddr.c  --  Data-dependent memory-bus "antenna" transmitter for Raspberry Pi 5.
 *
 * Idea (after Kuhn & Anderson 1998 "Soft Tempest", and Berke Durak's
 * lambda-diode PCI/mem experiments, 1999): write 32-/64-bit words whose bits
 * are either all-zeros (0x00..) or all-ones (0xFF..) to a DRAM buffer in a tight
 * loop. All data lines swing together, so the interconnect radiates a square-wave
 * carrier at (store rate)/2 plus odd harmonics. Keying between an all-ones burst
 * and an all-zeros (quiet) burst gives OOK; using two different burst *rates*
 * gives 2-FSK. A near-field H-probe over the LPDDR4X package or the PCIe/RP1 area,
 * or a wideband SDR, recovers it.
 *
 * This program supplies a KNOWN, PERIODIC signal on purpose. That is the whole
 * point of doing it before the LLM work: you learn which frequency to sit the
 * analyzer on, with the clocks pinned so DVFS is not a variable.
 *
 * GPIO frame trigger: a pin is raised for the duration of each transmitted frame
 * so the receiver can average many identical frames and align symbols. Uses
 * libgpiod v2 (Pi 5 GPIO is behind the RP1 chip; RPi.GPIO / direct BCM register
 * pokes do NOT work).
 *
 * Build:  see Makefile  (gcc -O2 ... -lgpiod)
 * Run:    sudo ./tx_ddr  (root or gpio/mem perms; see README)
 *
 * SAFETY: this only writes to its own malloc'd/ mmap'd anonymous memory. It does
 * NOT poke /dev/mem or physical PCI addresses (Durak's tempest-mem could hang a
 * box with a bad address). Keep it that way unless you know exactly what you are
 * doing.
 */

#define _GNU_SOURCE
#include <stdio.h>
#include <stdlib.h>
#include <stdint.h>
#include <string.h>
#include <stdbool.h>
#include <unistd.h>
#include <sched.h>
#include <time.h>
#include <getopt.h>
#include <errno.h>

#include <gpiod.h>   /* libgpiod v2 */

/* ----- tunables (all overridable on the command line) ----- */
#define DEFAULT_BUF_BYTES   (8u * 1024u * 1024u) /* >> L2/L3 so stores spill to DRAM */
#define DEFAULT_GPIO_CHIP   "/dev/gpiochip0"     /* RP1 bank; confirm with `gpioinfo` */
#define DEFAULT_TRIG_LINE   17                   /* BCM17, frame trigger */
#define DEFAULT_BIT_LINE    27                   /* BCM27, optional per-symbol toggle */
#define DEFAULT_REPS        2000                 /* frames to send */

/* A "symbol" is a burst of `stores` streaming writes. We alternate the fill
 * pattern (all-ones vs all-zeros) per word to synthesize a square wave; the
 * carrier is set by how fast we can push stores, divided by 2. We cannot set an
 * exact Hz from C, so we SWEEP burst length / inserted delay and read the carrier
 * off the analyzer. Keep it simple: OOK = ones-burst (mark) vs zeros-burst (space).
 */

enum mod { MOD_OOK, MOD_CARRIER_ONLY, MOD_FSK };

#define MAX_FREQS 8

struct cfg {
    size_t   buf_bytes;
    unsigned reps;
    unsigned stores_per_symbol; /* length of each mark/space burst (OOK) */
    double   symbol_ms;         /* if >0, calibrate stores to this symbol duration */
    unsigned gap_us;            /* idle gap between symbols (space for OOK-off) */
    /* FSK: data selects the *frequency* of a periodic memory-access tone. The
     * emitted fundamental f = 1/period; a small fixed "tick" burst each period is
     * the thing that radiates, the rest of the period is a busy-wait. Loop count
     * (tick size) and sleep (the wait) set f, exactly as on the whiteboard. */
    double   freqs[MAX_FREQS];  /* tone table; bit '0'->freqs[0], '1'->freqs[1] */
    int      nfreqs;
    double   dwell_ms;          /* how long to hold each symbol's tone */
    unsigned tick_words;        /* words written per period (the radiating blip) */
    int      trig_line;
    int      bit_line;
    const char *chip_path;
    const char *bits;           /* ASCII '0'/'1' payload, repeated each frame */
    enum mod mod;
    int      cpu;               /* pin to this core */
};

/* Non-temporal store so the value actually reaches DRAM instead of parking in L1.
 * On AArch64, STNP is the streaming (non-temporal) store pair; it writes two
 * 64-bit registers, i.e. a 16-byte line, so `p` MUST be 16-byte aligned or the
 * core takes a SIGBUS. Callers step by even word indices to keep that invariant. */
static inline void nt_store_pair(volatile uint64_t *p, uint64_t v)
{
    asm volatile("stnp %0, %0, [%1]" :: "r"(v), "r"(p) : "memory");
}

/* Fill `n_words` 64-bit words at base with `v`, using non-temporal stores, then
 * a barrier so the burst is bounded in time. */
static void burst(volatile uint64_t *base, size_t n_words, uint64_t v)
{
    for (size_t i = 0; i < n_words; i += 8) {
        nt_store_pair(base + i + 0, v);
        nt_store_pair(base + i + 2, v);
        nt_store_pair(base + i + 4, v);
        nt_store_pair(base + i + 6, v);
    }
    asm volatile("dsb st" ::: "memory"); /* drain store buffer */
}

static void pin_cpu(int cpu)
{
    if (cpu < 0) return;
    cpu_set_t set;
    CPU_ZERO(&set);
    CPU_SET(cpu, &set);
    if (sched_setaffinity(0, sizeof(set), &set) != 0)
        perror("sched_setaffinity (continuing unpinned)");
}

/* Parse a number with an optional SI suffix (k/K, m/M, g/G) so command-line
 * frequencies match the runbook's notation, e.g. "1M" -> 1e6, "500k" -> 5e5.
 * Plain strtod() stops at the letter and silently yields 1, 500, etc. */
static double parse_si(const char *s)
{
    char *end = 0;
    double v = strtod(s, &end);
    if (end && *end) {
        switch (*end) {
        case 'k': case 'K': v *= 1e3; break;
        case 'm': case 'M': v *= 1e6; break;
        case 'g': case 'G': v *= 1e9; break;
        default: break;
        }
    }
    return v;
}

static void busy_wait_us(unsigned us)
{
    if (!us) return;
    struct timespec t0, t1;
    clock_gettime(CLOCK_MONOTONIC, &t0);
    double target = us * 1000.0;
    do {
        clock_gettime(CLOCK_MONOTONIC, &t1);
    } while ((t1.tv_sec - t0.tv_sec) * 1e9 + (t1.tv_nsec - t0.tv_nsec) < target);
}

int main(int argc, char **argv)
{
    struct cfg c = {
        .buf_bytes = DEFAULT_BUF_BYTES,
        .reps = DEFAULT_REPS,
        .stores_per_symbol = 4096,
        .symbol_ms = 0.0,
        .gap_us = 0,
        .freqs = {100000.0, 150000.0}, /* default 2-FSK: 100 kHz / 150 kHz */
        .nfreqs = 2,
        .dwell_ms = 20.0,
        .tick_words = 64,              /* 512 B blip per period */
        .trig_line = DEFAULT_TRIG_LINE,
        .bit_line = DEFAULT_BIT_LINE,
        .chip_path = DEFAULT_GPIO_CHIP,
        .bits = "10110100", /* distinctive, non-symmetric preamble-ish default */
        .mod = MOD_OOK,
        .cpu = 2,
    };

    static struct option opts[] = {
        {"reps",    required_argument, 0, 'r'},
        {"stores",  required_argument, 0, 's'},
        {"symbol-ms", required_argument, 0, 'S'},
        {"fsk",     required_argument, 0, 'F'},
        {"dwell",   required_argument, 0, 'D'},
        {"tick",    required_argument, 0, 'T'},
        {"gap",     required_argument, 0, 'g'},
        {"bits",    required_argument, 0, 'b'},
        {"buf",     required_argument, 0, 'm'},
        {"trig",    required_argument, 0, 't'},
        {"bitpin",  required_argument, 0, 'p'},
        {"chip",    required_argument, 0, 'c'},
        {"cpu",     required_argument, 0, 'u'},
        {"carrier", no_argument,       0, 'C'},
        {"help",    no_argument,       0, 'h'},
        {0,0,0,0}
    };
    int ch;
    while ((ch = getopt_long(argc, argv, "r:s:S:F:D:T:g:b:m:t:p:c:u:Ch", opts, 0)) != -1) {
        switch (ch) {
        case 'r': c.reps = strtoul(optarg,0,0); break;
        case 's': c.stores_per_symbol = strtoul(optarg,0,0); break;
        case 'S': c.symbol_ms = strtod(optarg,0); break;
        case 'F': {
            c.mod = MOD_FSK;
            c.nfreqs = 0;
            char *tmp = strdup(optarg), *tok, *save = 0;
            for (tok = strtok_r(tmp, ",", &save); tok && c.nfreqs < MAX_FREQS;
                 tok = strtok_r(0, ",", &save))
                c.freqs[c.nfreqs++] = parse_si(tok);
            free(tmp);
            if (c.nfreqs < 2) { fprintf(stderr, "--fsk needs >=2 freqs\n"); return 2; }
            break;
        }
        case 'D': c.dwell_ms = strtod(optarg,0); break;
        case 'T': c.tick_words = strtoul(optarg,0,0); break;
        case 'g': c.gap_us = strtoul(optarg,0,0); break;
        case 'b': c.bits = optarg; break;
        case 'm': c.buf_bytes = strtoull(optarg,0,0); break;
        case 't': c.trig_line = atoi(optarg); break;
        case 'p': c.bit_line = atoi(optarg); break;
        case 'c': c.chip_path = optarg; break;
        case 'u': c.cpu = atoi(optarg); break;
        case 'C': c.mod = MOD_CARRIER_ONLY; break;
        case 'h':
        default:
            fprintf(stderr,
              "usage: %s [opts]\n"
              "  -r --reps N       frames to send (default %u)\n"
              "  -s --stores N     streaming stores per symbol burst (default 4096)\n"
              "  -S --symbol-ms MS calibrate --stores so one mark lasts ~MS ms\n"
              "                    (use for a swept spectrum analyzer; try 2-5 ms)\n"
              "  -g --gap US       idle gap between symbols, microseconds (default 0)\n"
              "  FSK mode (data sets the emitted FREQUENCY; best for a bare SA):\n"
              "  -F --fsk f0,f1[,..] tone per bit in Hz; '0'->f0 '1'->f1 (default 1e5,1.5e5)\n"
              "  -D --dwell MS     hold each symbol's tone for MS ms (default 20)\n"
              "  -T --tick WORDS   64-bit words written per period, the blip (default 64)\n"
              "  -b --bits STR     ASCII 0/1 payload per frame (default 10110100)\n"
              "  -m --buf BYTES    DRAM buffer size, must exceed cache (default 8MiB)\n"
              "  -t --trig BCM     GPIO frame-trigger line (default 17)\n"
              "  -p --bitpin BCM   GPIO per-symbol toggle line (default 27, -1 disables)\n"
              "  -c --chip PATH    gpiochip path (default /dev/gpiochip0)\n"
              "  -u --cpu N        pin to CPU core N (default 2; use an isolcpu)\n"
              "  -C --carrier      emit continuous carrier only (tune the analyzer)\n",
              argv[0], DEFAULT_REPS);
            return ch=='h'?0:2;
        }
    }

    pin_cpu(c.cpu);

    /* page-aligned DRAM buffer */
    void *raw = NULL;
    if (posix_memalign(&raw, 4096, c.buf_bytes) != 0) {
        perror("posix_memalign"); return 1;
    }
    memset(raw, 0, c.buf_bytes); /* fault pages in now, not mid-transmit */
    volatile uint64_t *buf = (volatile uint64_t*)raw;
    size_t words = c.buf_bytes / sizeof(uint64_t);
    unsigned stores = c.stores_per_symbol;
    if (stores > words) stores = words;

    /* Optional: size a symbol to a target wall-clock duration so a swept
     * spectrum analyzer can follow it in zero-span. Time a reference burst,
     * then scale. Reallocate a bigger buffer if the target needs more words
     * than the current one holds (burst() writes sequentially, no wrap). */
    if (c.symbol_ms > 0.0) {
        const uint64_t ONES = ~0ULL;
        /* warm up, then time a burst of the current `stores` words */
        burst(buf, stores, ONES);
        struct timespec a, b;
        double ns_per_store = 0.0;
        for (int trial = 0; trial < 5; ++trial) {
            clock_gettime(CLOCK_MONOTONIC, &a);
            burst(buf, stores, ONES);
            clock_gettime(CLOCK_MONOTONIC, &b);
            double ns = (b.tv_sec - a.tv_sec) * 1e9 + (b.tv_nsec - a.tv_nsec);
            double per = ns / (double)stores;
            if (trial == 0 || per < ns_per_store) ns_per_store = per; /* best (least preempted) */
        }
        double target_ns = c.symbol_ms * 1e6;
        double want = target_ns / ns_per_store;
        size_t want_stores = (size_t)want;
        want_stores = (want_stores / 8) * 8;        /* burst() steps by 8 */
        if (want_stores < 8) want_stores = 8;

        if (want_stores > words) {
            /* grow buffer to hold the longer burst (round up to 2 MiB) */
            size_t need_bytes = want_stores * sizeof(uint64_t);
            size_t new_bytes = ((need_bytes + (2u<<20) - 1) / (2u<<20)) * (2u<<20);
            void *nraw = NULL;
            if (posix_memalign(&nraw, 4096, new_bytes) != 0) {
                perror("posix_memalign (symbol-ms grow)"); free(raw); return 1;
            }
            memset(nraw, 0, new_bytes);
            free(raw);
            raw = nraw;
            buf = (volatile uint64_t*)raw;
            c.buf_bytes = new_bytes;
            words = new_bytes / sizeof(uint64_t);
        }
        stores = (unsigned)(want_stores > words ? words : want_stores);
        fprintf(stderr,
            "tx_ddr: calibrated %.3g ns/store -> stores=%u for ~%.2f ms/symbol "
            "(buf now %zu MiB)\n",
            ns_per_store, stores, (stores * ns_per_store) / 1e6, c.buf_bytes>>20);
    }

    /* ---- GPIO setup (libgpiod v2) ---- */
    struct gpiod_chip *chip = gpiod_chip_open(c.chip_path);
    if (!chip) { perror("gpiod_chip_open"); return 1; }

    struct gpiod_line_settings *ls = gpiod_line_settings_new();
    gpiod_line_settings_set_direction(ls, GPIOD_LINE_DIRECTION_OUTPUT);
    gpiod_line_settings_set_output_value(ls, GPIOD_LINE_VALUE_INACTIVE);

    unsigned int offs[2];
    int noff = 0;
    offs[noff++] = (unsigned)c.trig_line;
    if (c.bit_line >= 0) offs[noff++] = (unsigned)c.bit_line;

    struct gpiod_line_config *lc = gpiod_line_config_new();
    gpiod_line_config_add_line_settings(lc, offs, noff, ls);

    struct gpiod_request_config *rc = gpiod_request_config_new();
    gpiod_request_config_set_consumer(rc, "tx_ddr");

    struct gpiod_line_request *req = gpiod_chip_request_lines(chip, rc, lc);
    if (!req) { perror("gpiod_chip_request_lines"); return 1; }

    #define SET(line, val) \
        gpiod_line_request_set_value(req, (unsigned)(line), \
            (val) ? GPIOD_LINE_VALUE_ACTIVE : GPIOD_LINE_VALUE_INACTIVE)

    const uint64_t ONES = ~0ULL;
    const uint64_t ZERO = 0ULL;

    const char *modname = c.mod==MOD_OOK ? "OOK"
                        : c.mod==MOD_FSK ? "FSK" : "carrier-only";
    fprintf(stderr, "tx_ddr: reps=%u stores/sym=%u gap=%uus bits='%s' buf=%zuMiB cpu=%d mod=%s\n",
            c.reps, stores, c.gap_us, c.bits, c.buf_bytes>>20, c.cpu, modname);

    if (c.mod == MOD_CARRIER_ONLY) {
        /* Continuous square-wave carrier: alternate ones/zeros words forever-ish.
         * Use this first to find the peak on the analyzer. Ctrl-C to stop. */
        SET(c.trig_line, 1);
        /* round the usable window down to a multiple of 4 words (32 B) so every
         * index we form is 16-byte aligned, as STNP requires */
        size_t span = (words / 4) * 4;
        for (unsigned long long k = 0; ; ++k) {
            /* Alternate ones/zeros every 16-byte STNP line to make a square wave. */
            for (unsigned i = 0; i < stores; i += 4) {
                size_t idx = (size_t)i % span;       /* multiple of 4 -> 16B aligned */
                nt_store_pair(buf + idx,     ONES);  /* +0  bytes */
                nt_store_pair(buf + idx + 2, ZERO);  /* +16 bytes */
            }
            asm volatile("dsb st" ::: "memory");
            if ((k & 0xFFFF) == 0 && access("/tmp/tx_stop", F_OK) == 0) break;
        }
        SET(c.trig_line, 0);
        goto done;
    }

    if (c.mod == MOD_FSK) {
        /* Data sets the emitted FREQUENCY (the professor's loop-count/sleep idea).
         * Each period we write a small fixed "tick" burst (the radiating blip),
         * then busy-wait so the period = 1/f. Holding f for `dwell_ms` puts a line
         * at f (plus a harmonic comb) on the spectrum analyzer; the next symbol
         * moves the line. Read it with max-hold over a span covering the tones. */
        unsigned tick = (c.tick_words / 8) * 8;      /* burst() steps by 8 */
        if (tick < 8) tick = 8;
        if (tick > words) tick = (unsigned)((words / 8) * 8);

        /* time one tick so we know how long to busy-wait for a given period */
        burst(buf, tick, ONES);                       /* warm up */
        struct timespec a, b;
        clock_gettime(CLOCK_MONOTONIC, &a);
        for (int w = 0; w < 16; ++w) burst(buf, tick, ONES);
        clock_gettime(CLOCK_MONOTONIC, &b);
        double tick_ns = ((b.tv_sec-a.tv_sec)*1e9 + (b.tv_nsec-a.tv_nsec)) / 16.0;
        fprintf(stderr, "tx_ddr: FSK tick=%u words ~%.0f ns; freqs:", tick, tick_ns);
        for (int i = 0; i < c.nfreqs; ++i) fprintf(stderr, " %.0f", c.freqs[i]);
        fprintf(stderr, " Hz; dwell=%.1f ms\n", c.dwell_ms);
        for (int i = 0; i < c.nfreqs; ++i) {
            double per_ns = 1e9 / c.freqs[i];
            if (per_ns <= tick_ns)
                fprintf(stderr, "  [warn] f=%.0f Hz period %.0f ns < tick %.0f ns; "
                        "tone will cap near %.0f Hz (shrink --tick to go higher)\n",
                        c.freqs[i], per_ns, tick_ns, 1e9/tick_ns);
        }

        size_t nb = strlen(c.bits);
        for (unsigned rep = 0; rep < c.reps; ++rep) {
            SET(c.trig_line, 1);
            for (size_t i = 0; i < nb; ++i) {
                int sym = (c.bits[i] == '1') ? 1 : 0;   /* 2-FSK keyed by the bit */
                if (c.bit_line >= 0) SET(c.bit_line, sym);
                double per_ns = 1e9 / c.freqs[sym];
                double wait_ns = per_ns - tick_ns;
                if (wait_ns < 0) wait_ns = 0;           /* clamp: tick-limited */
                struct timespec t0;
                clock_gettime(CLOCK_MONOTONIC, &t0);
                double deadline = (double)t0.tv_sec*1e9 + t0.tv_nsec; /* next edge */
                double end = deadline + c.dwell_ms * 1e6;
                struct timespec now;
                do {
                    burst(buf, tick, ONES);             /* the radiating blip */
                    deadline += per_ns;                 /* absolute, no drift */
                    /* busy-wait to the period boundary */
                    do {
                        clock_gettime(CLOCK_MONOTONIC, &now);
                    } while (((double)now.tv_sec*1e9 + now.tv_nsec) < deadline);
                } while (((double)now.tv_sec*1e9 + now.tv_nsec) < end);
                (void)wait_ns;
            }
            if (c.bit_line >= 0) SET(c.bit_line, 0);
            SET(c.trig_line, 0);
            busy_wait_us(200);
        }
        goto done;
    }

    /* OOK: for each frame, raise trigger, then for each payload bit send a
     * mark (ones burst) or space (zeros burst / idle). */
    size_t nbits = strlen(c.bits);
    for (unsigned rep = 0; rep < c.reps; ++rep) {
        SET(c.trig_line, 1);                 /* frame start */
        for (size_t i = 0; i < nbits; ++i) {
            int one = (c.bits[i] == '1');
            if (c.bit_line >= 0) SET(c.bit_line, one);
            if (one) {
                burst(buf, stores, ONES);    /* mark: loud, data lines toggling */
            } else {
                /* space: keep the core busy but quiet on the bus (write zeros to
                 * a single cache line so DRAM stays idle), then optional gap */
                for (unsigned q = 0; q < stores; q += 8)
                    buf[0] = ZERO;           /* stays in L1, little DRAM traffic */
                asm volatile("dsb st" ::: "memory");
            }
            if (c.gap_us) busy_wait_us(c.gap_us);
        }
        if (c.bit_line >= 0) SET(c.bit_line, 0);
        SET(c.trig_line, 0);                 /* frame end */
        /* small inter-frame gap so the receiver can segment frames */
        busy_wait_us(200);
    }

done:
    gpiod_line_request_release(req);
    gpiod_request_config_free(rc);
    gpiod_line_config_free(lc);
    gpiod_line_settings_free(ls);
    gpiod_chip_close(chip);
    free(raw);
    return 0;
}
