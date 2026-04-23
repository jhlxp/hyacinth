#include <algorithm>
#include <cmath>
#include <filesystem>
#include <fstream>
#include <iomanip>
#include <iostream>
#include <sstream>
#include <stdexcept>
#include <string>
#include <unordered_map>
#include <utility>
#include <vector>

#include "scheduler.h"
#include "simulator.h"
#include "topology_reader.h"
#include "traffic_reader.h"

namespace {

struct LegacyLine {
    bool isRaw = false;
    std::string rawLine;
    std::vector<std::string> tokens;
    int groupId = -1;
    int flowIdInGroup = -1;
    bool hasNetworkFlow = false;
};

std::string trim(const std::string& s) {
    const size_t first = s.find_first_not_of(" \t\r\n");
    if (first == std::string::npos) {
        return "";
    }
    const size_t last = s.find_last_not_of(" \t\r\n");
    return s.substr(first, last - first + 1);
}

std::vector<std::string> splitWhitespace(const std::string& s) {
    std::istringstream iss(s);
    std::vector<std::string> out;
    std::string tok;
    while (iss >> tok) {
        out.push_back(tok);
    }
    return out;
}

std::string joinPathToken(const std::vector<int>& path) {
    std::ostringstream oss;
    oss << "path=";
    for (size_t i = 0; i < path.size(); ++i) {
        if (i > 0) {
            oss << ',';
        }
        oss << path[i];
    }
    return oss.str();
}

std::string joinTokens(const std::vector<std::string>& tokens) {
    std::ostringstream oss;
    for (size_t i = 0; i < tokens.size(); ++i) {
        if (i > 0) {
            oss << ' ';
        }
        oss << tokens[i];
    }
    return oss.str();
}

bool isHybridEpsOcsScheduler(const std::string& schedulerName) {
    return schedulerName.rfind("ocs_eps_", 0) == 0 || schedulerName == "strict_queue_greedy";
}

bool pathUsesEps(const std::vector<int>& path, int numTor) {
    for (int node : path) {
        if (node >= numTor) {
            return true;
        }
    }
    return false;
}

struct PairHash {
    std::size_t operator()(const std::pair<int, int>& p) const noexcept {
        const std::uint64_t hi = static_cast<std::uint32_t>(p.first);
        const std::uint64_t lo = static_cast<std::uint32_t>(p.second);
        return static_cast<std::size_t>((hi << 32U) ^ lo);
    }
};

std::unordered_map<std::string, std::string> parseNamedArgs(int argc, char* argv[]) {
    std::unordered_map<std::string, std::string> kv;
    for (int i = 1; i < argc; ++i) {
        const std::string key = argv[i];
        if (key.rfind("--", 0) != 0) {
            throw std::runtime_error("Invalid argument (expected --key): " + key);
        }
        if (i + 1 >= argc) {
            throw std::runtime_error("Missing value for argument: " + key);
        }
        const std::string value = argv[++i];
        kv[key.substr(2)] = value;
    }
    return kv;
}

template <typename T>
T parseValue(const std::unordered_map<std::string, std::string>& kv, const std::string& key);

template <>
int parseValue<int>(const std::unordered_map<std::string, std::string>& kv, const std::string& key) {
    auto it = kv.find(key);
    if (it == kv.end()) {
        throw std::runtime_error("Missing required argument: --" + key);
    }
    return std::stoi(it->second);
}

template <>
double parseValue<double>(const std::unordered_map<std::string, std::string>& kv, const std::string& key) {
    auto it = kv.find(key);
    if (it == kv.end()) {
        throw std::runtime_error("Missing required argument: --" + key);
    }
    return std::stod(it->second);
}

template <>
std::string parseValue<std::string>(
    const std::unordered_map<std::string, std::string>& kv,
    const std::string& key) {
    auto it = kv.find(key);
    if (it == kv.end()) {
        throw std::runtime_error("Missing required argument: --" + key);
    }
    return it->second;
}

template <typename T>
T parseOptional(
    const std::unordered_map<std::string, std::string>& kv,
    const std::string& key,
    const T& defaultValue);

template <>
int parseOptional<int>(
    const std::unordered_map<std::string, std::string>& kv,
    const std::string& key,
    const int& defaultValue) {
    auto it = kv.find(key);
    return (it == kv.end()) ? defaultValue : std::stoi(it->second);
}

template <>
double parseOptional<double>(
    const std::unordered_map<std::string, std::string>& kv,
    const std::string& key,
    const double& defaultValue) {
    auto it = kv.find(key);
    return (it == kv.end()) ? defaultValue : std::stod(it->second);
}

template <>
std::string parseOptional<std::string>(
    const std::unordered_map<std::string, std::string>& kv,
    const std::string& key,
    const std::string& defaultValue) {
    auto it = kv.find(key);
    return (it == kv.end()) ? defaultValue : it->second;
}

void printUsage(const char* prog) {
    std::cerr << "Usage:\n";
    std::cerr << "  " << prog
              << " --topo_file <path>"
              << " --traffic_in <legacy_trace_dep_file>"
              << " --traffic_out <routed_trace_dep_file>"
              << " --num_tor <int>"
              << " --num_eps <int>"
              << " --rate_tor_tor <double>"
              << " --rate_tor_eps <double>"
              << " [--scheduler <name>]"
              << " [--ksp_k <int>]"
              << " [--max_hops <int>]"
              << " [--max_candidates <int>]"
              << " [--small_flow_mode <percent|count_percent|value>]"
              << " [--small_flow_threshold <double>]\n";
}

}  // namespace

int main(int argc, char* argv[]) {
    if (argc < 2) {
        printUsage(argv[0]);
        return 1;
    }

    try {
        const auto kv = parseNamedArgs(argc, argv);

        const std::string topoFile = parseValue<std::string>(kv, "topo_file");
        const std::string trafficIn = parseValue<std::string>(kv, "traffic_in");
        const std::string trafficOut = parseValue<std::string>(kv, "traffic_out");
        const int numTor = parseValue<int>(kv, "num_tor");
        const int numEps = parseValue<int>(kv, "num_eps");
        const double rateTorTor = parseValue<double>(kv, "rate_tor_tor");
        const double rateTorEps = parseValue<double>(kv, "rate_tor_eps");

        flsim::SchedulerConfig schedulerCfg;
        schedulerCfg.name = parseOptional<std::string>(kv, "scheduler", "ocs_eps_pruned");
        schedulerCfg.kspK = parseOptional<int>(kv, "ksp_k", 4);
        schedulerCfg.maxHops = parseOptional<int>(kv, "max_hops", 5);
        schedulerCfg.maxCandidates = parseOptional<int>(kv, "max_candidates", 20);
        schedulerCfg.smallFlowMode = parseOptional<std::string>(kv, "small_flow_mode", "percent");
        schedulerCfg.smallFlowThreshold = parseOptional<double>(kv, "small_flow_threshold", 90.0);

        if (numTor <= 0) {
            throw std::runtime_error("num_tor must be > 0.");
        }
        if (numEps < 0) {
            throw std::runtime_error("num_eps must be >= 0.");
        }
        if (rateTorTor <= 0.0 || rateTorEps <= 0.0) {
            throw std::runtime_error("link rates must be > 0.");
        }

        const std::filesystem::path trafficInPath(trafficIn);
        if (!std::filesystem::exists(trafficInPath)) {
            throw std::runtime_error("traffic_in not found: " + trafficIn);
        }
        if (!std::filesystem::is_regular_file(trafficInPath)) {
            throw std::runtime_error("traffic_in must be a regular file: " + trafficIn);
        }

        const auto topo = flsim::readTopologyFile(topoFile);
        if (numTor + numEps > topo.N) {
            throw std::runtime_error("num_tor + num_eps exceeds total node count N.");
        }

        const int numAgg = topo.N - numTor - numEps;
        if (numAgg <= 0) {
            throw std::runtime_error("No Agg nodes found.");
        }

        const auto aggParentTor = flsim::inferAggParentTor(topo.adj, numTor, numEps);
        const auto rawTraffic = flsim::readTrafficFile(trafficIn, flsim::TrafficInputFormat::TraceDep6);
        const auto jobs = flsim::buildJobsFromTraffic(rawTraffic, aggParentTor);
        const auto coreCapacity = flsim::buildCoreCapacityMatrix(topo.adj, numTor, numEps, rateTorTor, rateTorEps);

        auto scheduler = flsim::createScheduler(schedulerCfg);
        flsim::FlowLevelSimulator simulator(coreCapacity, numTor, numEps, std::move(scheduler));
        const auto result = simulator.run(jobs);

        std::unordered_map<std::pair<int, int>, std::vector<int>, PairHash> keyToPath;
        keyToPath.reserve(result.scheduledFlows.size());
        for (const auto& sf : result.scheduledFlows) {
            const std::pair<int, int> key(sf.flow.jobId, sf.flow.flowId);
            if (keyToPath.find(key) != keyToPath.end()) {
                throw std::runtime_error(
                    "Duplicate (jobId,flowId) in scheduled result: (" +
                    std::to_string(key.first) + "," + std::to_string(key.second) + ")");
            }
            std::vector<int> path = sf.corePath;
            if (path.empty()) {
                path.push_back(sf.flow.torSrc);
            }
            keyToPath.emplace(key, std::move(path));
        }

        std::ifstream fin(trafficIn);
        if (!fin.is_open()) {
            throw std::runtime_error("Cannot open traffic_in for reconstruction: " + trafficIn);
        }

        std::vector<LegacyLine> lines;
        lines.reserve(rawTraffic.size());
        std::unordered_map<int, int> flowIdByGroup;
        int networkFlowCount = 0;

        std::string raw;
        int lineNo = 0;
        while (std::getline(fin, raw)) {
            ++lineNo;
            const std::string stripped = trim(raw);
            if (stripped.empty() || stripped[0] == '#') {
                LegacyLine rec;
                rec.isRaw = true;
                rec.rawLine = raw;
                lines.push_back(std::move(rec));
                continue;
            }

            auto tokens = splitWhitespace(stripped);
            if (tokens.size() < 5) {
                throw std::runtime_error(
                    "Invalid trace_dep line (need >=5 columns) at " +
                    std::to_string(lineNo) + ": " + raw);
            }

            const int groupId = std::stoi(tokens[4]);
            const double flowBytes = std::stod(tokens[2]);
            const int flowIdInGroup = flowIdByGroup[groupId]++;
            const bool hasNetwork = (flowBytes > 1e-12);
            if (hasNetwork) {
                ++networkFlowCount;
            }

            LegacyLine rec;
            rec.isRaw = false;
            rec.rawLine = raw;
            rec.tokens = std::move(tokens);
            rec.groupId = groupId;
            rec.flowIdInGroup = flowIdInGroup;
            rec.hasNetworkFlow = hasNetwork;
            lines.push_back(std::move(rec));
        }

        if (networkFlowCount != static_cast<int>(keyToPath.size())) {
            throw std::runtime_error(
                "Network flow count mismatch: input has " + std::to_string(networkFlowCount) +
                ", scheduler output has " + std::to_string(keyToPath.size()));
        }

        std::ofstream fout(trafficOut);
        if (!fout.is_open()) {
            throw std::runtime_error("Cannot open traffic_out for write: " + trafficOut);
        }

        for (const auto& rec : lines) {
            if (rec.isRaw) {
                fout << rec.rawLine << '\n';
                continue;
            }
            if (!rec.hasNetworkFlow) {
                fout << joinTokens(rec.tokens) << '\n';
                continue;
            }

            const std::pair<int, int> key(rec.groupId, rec.flowIdInGroup);
            const auto it = keyToPath.find(key);
            if (it == keyToPath.end()) {
                throw std::runtime_error(
                    "Missing path for network flow key=(" +
                    std::to_string(key.first) + "," + std::to_string(key.second) + ")");
            }
            fout << joinTokens(rec.tokens) << ' ' << joinPathToken(it->second) << '\n';
        }

        long long splitTotalFlows = 0;
        long long splitEpsFlows = 0;
        long long splitOcsFlows = 0;
        double splitTotalBytes = 0.0;
        double splitEpsBytes = 0.0;
        double splitOcsBytes = 0.0;
        constexpr double kTinyBytes = 1e-12;
        for (const auto& sf : result.scheduledFlows) {
            if (sf.sameTorBypass || sf.flow.bytes <= kTinyBytes) {
                continue;
            }
            ++splitTotalFlows;
            splitTotalBytes += sf.flow.bytes;
            if (pathUsesEps(sf.corePath, numTor)) {
                ++splitEpsFlows;
                splitEpsBytes += sf.flow.bytes;
            } else {
                ++splitOcsFlows;
                splitOcsBytes += sf.flow.bytes;
            }
        }

        const double epsFlowPct = (splitTotalFlows > 0)
                                      ? (100.0 * static_cast<double>(splitEpsFlows) /
                                         static_cast<double>(splitTotalFlows))
                                      : 0.0;
        const double ocsFlowPct = (splitTotalFlows > 0)
                                      ? (100.0 * static_cast<double>(splitOcsFlows) /
                                         static_cast<double>(splitTotalFlows))
                                      : 0.0;
        const double epsBytesPct = (splitTotalBytes > kTinyBytes)
                                       ? (100.0 * splitEpsBytes / splitTotalBytes)
                                       : 0.0;
        const double ocsBytesPct = (splitTotalBytes > kTinyBytes)
                                       ? (100.0 * splitOcsBytes / splitTotalBytes)
                                       : 0.0;

        double solveMs = 0.0;
        for (const auto& st : result.solveCalls) {
            solveMs += st.solveTimeMs;
        }
        const int numSolveCalls = static_cast<int>(result.solveCalls.size());
        const double avgSolveMs = (numSolveCalls > 0)
                                      ? (solveMs / static_cast<double>(numSolveCalls))
                                      : 0.0;

        std::cout << "[OK] routed traffic written: " << trafficOut << '\n';
        std::cout << "[OK] scheduler=" << schedulerCfg.name
                  << ", coflows=" << jobs.size()
                  << ", network_flows=" << networkFlowCount
                  << ", solveTimeMs=" << solveMs << '\n';
        std::cout << "scheduler = " << schedulerCfg.name << '\n';
        std::cout << "topo_file = " << topoFile << '\n';
        std::cout << "traffic_in = " << trafficIn << '\n';
        std::cout << "traffic_out = " << trafficOut << '\n';
        std::cout << "numSolveCalls = " << numSolveCalls << '\n';
        std::cout << "solveTimeMs = " << solveMs << '\n';
        std::cout << "avgSolveTimeMs = " << avgSolveMs << '\n';
        if (isHybridEpsOcsScheduler(schedulerCfg.name)) {
            std::cout << std::fixed << std::setprecision(4);
            std::cout << "[MIX] small_flow_mode = " << schedulerCfg.smallFlowMode
                      << ", small_flow_threshold = " << schedulerCfg.smallFlowThreshold << '\n';
            std::cout << "[MIX] network_flows = " << splitTotalFlows
                      << ", network_bytes = " << splitTotalBytes << '\n';
            std::cout << "[MIX] eps_flows = " << splitEpsFlows
                      << ", ocs_flows = " << splitOcsFlows
                      << ", eps_flow_pct = " << epsFlowPct
                      << ", ocs_flow_pct = " << ocsFlowPct << '\n';
            std::cout << "[MIX] eps_bytes = " << splitEpsBytes
                      << ", ocs_bytes = " << splitOcsBytes
                      << ", eps_bytes_pct = " << epsBytesPct
                      << ", ocs_bytes_pct = " << ocsBytesPct << '\n';
            std::cout.unsetf(std::ios::floatfield);
        }
        return 0;
    } catch (const std::exception& e) {
        std::cerr << "Fatal error: " << e.what() << "\n\n";
        printUsage(argv[0]);
        return 1;
    }
}
