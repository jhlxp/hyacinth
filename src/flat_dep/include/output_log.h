#ifndef OUTPUT_LOG_H
#define OUTPUT_LOG_H

// ================================
// Prevent broken macros from qcn.h
// ================================
#ifdef max
#undef max
#endif

#ifdef min
#undef min
#endif

#include <string>
#include <cstdio>
#include <ios>
#include <iomanip>
#include <chrono>
#include <ctime>
#include <cstring>

class OutputLogger {
public:
    OutputLogger()
        : FLUSH_EVERY(10000),
          line_count(0),
          total_flushed_lines(0),
          CAP(4 * 1024 * 1024),
          initialized(false)
    {}

    // =====================================================
    // init(): Overwrite file once, start new logging session
    // =====================================================
    void init(const std::string& filename,
              size_t flush_every,
              size_t buf_capacity)
    {
        file        = filename;
        FLUSH_EVERY = flush_every;
        CAP         = buf_capacity;

        // Overwrite old output file
        FILE* fp = fopen(file.c_str(), "wb");
        if (fp) fclose(fp);

        buf.clear();
        buf.reserve(CAP);

        line_count = 0;
        total_flushed_lines = 0;
        last_flush_time = steady_now();

        initialized = true;
    }

    // =====================================================
    // cout-like operator<<
    // =====================================================
    template<typename T>
    OutputLogger& operator<<(const T& v) {
        if (!initialized) return *this;
        this->appendValue(v);
        this->checkBufferUsage();
        return *this;
    }

    OutputLogger& operator<<(const char* s) {
        if (!initialized) return *this;
        this->appendString(s);
        this->checkBufferUsage();
        return *this;
    }

    OutputLogger& operator<<(char c) {
        if (!initialized) return *this;
        buf.push_back(c);
        if (c == '\n') this->onNewLine();
        this->checkBufferUsage();
        return *this;
    }

    // manipulators like std::hex, std::dec
    OutputLogger& operator<<(std::ios_base& (*manip)(std::ios_base&)) {
        return *this;
    }

    // =====================================================
    // final flush
    // =====================================================
    void finalFlush() {
        if (!initialized || buf.empty()) return;

        size_t bytes = buf.size();
        size_t lines = line_count;

        FILE* fp = fopen(file.c_str(), "ab");
        fwrite(buf.data(), 1, bytes, fp);
        fclose(fp);

        total_flushed_lines += lines;

        print_flush_message("Final flush", lines, bytes);

        buf.clear();
        line_count = 0;
    }

private:
    // =====================================================
    // Internal Members
    // =====================================================
    std::string buf;
    std::string file;
    size_t FLUSH_EVERY;
    size_t line_count;
    size_t total_flushed_lines;
    size_t CAP;
    bool initialized;

    using steady_clock_t = std::chrono::steady_clock;
    steady_clock_t::time_point last_flush_time;

    // =====================================================
    // Time Helpers
    // =====================================================
    inline steady_clock_t::time_point steady_now() {
        return steady_clock_t::now();
    }

    inline double seconds_since(steady_clock_t::time_point a,
                                steady_clock_t::time_point b) {
        using namespace std::chrono;
        return duration<double>(b - a).count();
    }

    // Timestamp format: YYYY-MM-DD HH:MM:SS.mmm
    std::string timestamp_now() {
        using namespace std::chrono;
        auto now = system_clock::now();
        auto t = system_clock::to_time_t(now);

        std::tm tm;
        localtime_r(&t, &tm);

        char base[64];
        std::strftime(base, sizeof(base), "%Y-%m-%d %H:%M:%S", &tm);

        auto ms = duration_cast<milliseconds>(now.time_since_epoch()) % 1000;

        char out[80];
        std::snprintf(out, sizeof(out), "%s.%03lld",
                      base, (long long)ms.count());
        return out;
    }

    // =====================================================
    // Core flush function
    // =====================================================
    inline void flushNow() {
        if (buf.empty()) return;

        size_t bytes = buf.size();
        size_t lines = line_count;

        FILE* fp = fopen(file.c_str(), "ab");
        fwrite(buf.data(), 1, bytes, fp);
        fclose(fp);

        total_flushed_lines += lines;

        print_flush_message("Flushed", lines, bytes);

        buf.clear();
        line_count = 0;
    }

    // Print flush log with timestamp + Δ
    void print_flush_message(const char* tag, size_t lines, size_t bytes) {
        auto t = steady_now();
        double delta = seconds_since(last_flush_time, t);
        last_flush_time = t;

        double rss_gb = get_self_rss_gb();

        // printf("[Logger] %s  %s %zu lines (%zu bytes). Total: %zu  Δ=%.3fs\n",
        //        timestamp_now().c_str(),
        //        tag, lines, bytes, total_flushed_lines, delta);

        printf("[Logger] %s  %s %zu lines (%zu bytes). Total: %zu  Δ=%.3fs  RSS=%.3f GB\n",
            timestamp_now().c_str(),
            tag, lines, bytes, total_flushed_lines, delta,
            rss_gb);
    }

    inline void onNewLine() {
        line_count++;
        if (line_count >= FLUSH_EVERY) {
            this->flushNow();
        }
    }

    // =====================================================
    // Append Helpers
    // =====================================================
    template<typename T>
    void appendValue(const T& v) {
        buf.append(std::to_string(v));
    }

    void appendString(const char* s) {
        while (*s) {
            char c = *s++;
            buf.push_back(c);
            if (c == '\n')
                this->onNewLine();
        }
    }

    // =====================================================
    // Buffer usage
    // =====================================================
    inline void checkBufferUsage() {
        if (buf.size() >= (CAP * 8) / 10) { // 80%
            this->flushNow();
        }
    }

    double get_self_rss_gb() {
        FILE* fp = fopen("/proc/self/status", "r");
        if (!fp) return 0.0;

        char line[256];
        size_t rss_kb = 0;

        while (fgets(line, sizeof(line), fp)) {
            if (strncmp(line, "VmRSS:", 6) == 0) {
                sscanf(line + 6, "%zu", &rss_kb);
                break;
            }
        }

        fclose(fp);

        return rss_kb / (1024.0 * 1024.0);
    }

};

// =============================================
// Global instance (defined in main.cpp)
// =============================================
extern OutputLogger OUTPUT_LOG;

// Convenience macro
#define OUTPUT_LOG_FLUSH() OUTPUT_LOG.finalFlush()

#endif // OUTPUT_LOG_H
