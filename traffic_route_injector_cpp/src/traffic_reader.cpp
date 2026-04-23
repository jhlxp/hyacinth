#include "traffic_reader.h"

#include <algorithm>
#include <cmath>
#include <filesystem>
#include <fstream>
#include <sstream>
#include <stdexcept>
#include <unordered_map>
#include <unordered_set>
#include <vector>

namespace flsim {
namespace {

std::vector<int> parseDepsTokens(const std::vector<std::string>& tokens,
                                 size_t beginIdx,
                                 int lineNo) {
    std::vector<int> deps;
    for (size_t i = beginIdx; i < tokens.size(); ++i) {
        std::string token = tokens[i];
        if (token == "-") {
            continue;
        }
        std::replace(token.begin(), token.end(), ',', ' ');
        std::istringstream iss(token);
        int dep = -1;
        while (iss >> dep) {
            if (dep < 0) {
                throw std::runtime_error("Invalid negative dep id at line " + std::to_string(lineNo));
            }
            deps.push_back(dep);
        }
    }
    std::sort(deps.begin(), deps.end());
    deps.erase(std::unique(deps.begin(), deps.end()), deps.end());
    return deps;
}

bool tryParseDouble(const std::string& s, double& out) {
    std::istringstream iss(s);
    iss >> out;
    return iss && iss.eof();
}

TrafficInputFormat detectFormat(const std::vector<std::string>& tokens) {
    // 5-column trace_dep is valid: src dst bytes comp_or_start group
    if (tokens.size() == 5) {
        return TrafficInputFormat::TraceDep6;
    }
    if (tokens.size() < 5) {
        return TrafficInputFormat::Flow6;
    }
    if (tokens[5] == "-" || tokens[5].find(',') != std::string::npos) {
        return TrafficInputFormat::TraceDep6;
    }
    double maybe = 0.0;
    if (!tryParseDouble(tokens[5], maybe)) {
        return TrafficInputFormat::TraceDep6;
    }
    return TrafficInputFormat::Flow6;
}

TrafficEntry parseFlowFormatLine(const std::vector<std::string>& tokens,
                                 int lineNo) {
    TrafficEntry e;
    e.jobId = std::stoi(tokens[0]);
    e.flowId = std::stoi(tokens[1]);
    e.aggSrc = std::stoi(tokens[2]);
    e.aggDst = std::stoi(tokens[3]);
    e.bytes = std::stod(tokens[4]);
    e.startTime = std::stod(tokens[5]);
    if (tokens.size() >= 7) {
        e.modelId = std::stoi(tokens[6]);
    }
    if (tokens.size() >= 8) {
        e.roundId = std::stoi(tokens[7]);
    }
    if (tokens.size() >= 9) {
        e.groupId = std::stoi(tokens[8]);
    }
    if (tokens.size() >= 10) {
        e.compUs = std::stod(tokens[9]);
    }
    if (tokens.size() >= 11) {
        e.deps = parseDepsTokens(tokens, 10, lineNo);
    }
    return e;
}

TrafficEntry parseTraceDepFormatLine(const std::vector<std::string>& tokens,
                                     int lineNo,
                                     std::unordered_map<int, int>& flowIdByGroup) {
    // Trace-dep format:
    // src dst bytes comp_us group [deps...|-]
    TrafficEntry e;
    e.aggSrc = std::stoi(tokens[0]);
    e.aggDst = std::stoi(tokens[1]);
    e.bytes = std::stod(tokens[2]);
    e.compUs = std::stod(tokens[3]);
    e.groupId = std::stoi(tokens[4]);
    e.deps = parseDepsTokens(tokens, 5, lineNo);

    e.jobId = e.groupId;
    e.flowId = flowIdByGroup[e.groupId]++;
    e.startTime = 0.0;
    return e;
}

}  // namespace

std::vector<TrafficEntry> readTrafficSingleFile(const std::string& filename,
                                                TrafficInputFormat format) {
    std::ifstream fin(filename);
    if (!fin.is_open()) {
        throw std::runtime_error("Cannot open traffic file: " + filename);
    }

    std::vector<TrafficEntry> traffic;
    std::string line;
    int lineNo = 0;
    TrafficInputFormat effectiveFormat = format;
    std::unordered_map<int, int> flowIdByGroup;

    while (std::getline(fin, line)) {
        ++lineNo;
        if (line.empty()) {
            continue;
        }
        if (line[0] == '#') {
            continue;
        }

        std::istringstream tokenIss(line);
        std::vector<std::string> tokens;
        std::string token;
        while (tokenIss >> token) {
            tokens.push_back(token);
        }
        if (tokens.empty()) {
            continue;
        }

        try {
            if (effectiveFormat == TrafficInputFormat::Auto) {
                effectiveFormat = detectFormat(tokens);
            }

            TrafficEntry e;
            if (effectiveFormat == TrafficInputFormat::TraceDep6) {
                if (tokens.size() < 5) {
                    throw std::runtime_error("Invalid trace_dep line (need >=5 columns) at " +
                                             std::to_string(lineNo) + ": " + line);
                }
                e = parseTraceDepFormatLine(tokens, lineNo, flowIdByGroup);
            } else {
                if (tokens.size() < 6) {
                    throw std::runtime_error("Invalid flow line (need >=6 columns) at " +
                                             std::to_string(lineNo) + ": " + line);
                }
                e = parseFlowFormatLine(tokens, lineNo);
            }
            traffic.push_back(e);
        } catch (const std::exception&) {
            throw std::runtime_error("Invalid traffic line at " + std::to_string(lineNo) + ": " + line);
        }
    }

    return traffic;
}

std::vector<TrafficEntry> readTrafficFile(const std::string& filename,
                                          TrafficInputFormat format) {
    namespace fs = std::filesystem;
    fs::path inputPath(filename);
    if (!fs::exists(inputPath)) {
        throw std::runtime_error("Traffic path does not exist: " + filename);
    }

    if (fs::is_regular_file(inputPath)) {
        return readTrafficSingleFile(filename, format);
    }

    if (!fs::is_directory(inputPath)) {
        throw std::runtime_error("Traffic path is neither a file nor a directory: " + filename);
    }

    std::vector<fs::path> files;
    for (const auto& entry : fs::directory_iterator(inputPath)) {
        if (!entry.is_regular_file()) {
            continue;
        }
        const auto ext = entry.path().extension().string();
        if (ext == ".txt") {
            files.push_back(entry.path());
        }
    }
    std::sort(files.begin(), files.end());
    if (files.empty()) {
        throw std::runtime_error("No .txt files found under traffic directory: " + filename);
    }

    std::vector<TrafficEntry> merged;
    int nextGlobalJobId = 0;
    int modelId = 0;
    for (const auto& p : files) {
        auto local = readTrafficSingleFile(p.string(), format);
        if (local.empty()) {
            ++modelId;
            continue;
        }

        std::vector<int> localJobIds;
        localJobIds.reserve(local.size());
        for (const auto& e : local) {
            localJobIds.push_back(e.jobId);
        }
        std::sort(localJobIds.begin(), localJobIds.end());
        localJobIds.erase(std::unique(localJobIds.begin(), localJobIds.end()), localJobIds.end());

        std::unordered_map<int, int> localToGlobalJob;
        localToGlobalJob.reserve(localJobIds.size());
        for (int oldId : localJobIds) {
            localToGlobalJob[oldId] = nextGlobalJobId++;
        }

        for (auto& e : local) {
            const int oldJobId = e.jobId;
            e.jobId = localToGlobalJob[oldJobId];
            for (auto& dep : e.deps) {
                const auto it = localToGlobalJob.find(dep);
                if (it == localToGlobalJob.end()) {
                    throw std::runtime_error(
                        "Dependency group/job id not found in the same file: " + p.string());
                }
                dep = it->second;
            }
            if (e.modelId < 0) {
                e.modelId = modelId;
            }
            if (e.groupId < 0) {
                e.groupId = oldJobId;
            }
            merged.push_back(std::move(e));
        }
        ++modelId;
    }

    return merged;
}

std::vector<Job> buildJobsFromTraffic(const std::vector<TrafficEntry>& traffic,
                                      const std::vector<int>& aggParentTor) {
    const int numAgg = static_cast<int>(aggParentTor.size());
    std::unordered_map<int, Job> byJob;
    byJob.reserve(traffic.size());

    for (const auto& tr : traffic) {
        auto it = byJob.find(tr.jobId);
        if (it == byJob.end()) {
            Job job;
            job.jobId = tr.jobId;
            job.startTime = tr.startTime;
            job.modelId = tr.modelId;
            job.roundId = tr.roundId;
            job.groupId = tr.groupId;
            job.computeTime = std::max(0.0, tr.compUs * 1e-6);
            job.deps = tr.deps;
            auto insert = byJob.emplace(tr.jobId, std::move(job));
            it = insert.first;
        } else {
            if (std::fabs(it->second.startTime - tr.startTime) > 1e-9) {
                throw std::runtime_error(
                    "Flows in the same jobId must share the same startTime. jobId=" +
                    std::to_string(tr.jobId));
            }
            it->second.computeTime = std::max(it->second.computeTime, std::max(0.0, tr.compUs * 1e-6));
        }

        Job& job = it->second;
        if (tr.modelId >= 0) {
            if (job.modelId < 0) {
                job.modelId = tr.modelId;
            } else if (job.modelId != tr.modelId) {
                throw std::runtime_error("Inconsistent modelId for jobId=" + std::to_string(tr.jobId));
            }
        }
        if (tr.roundId >= 0) {
            if (job.roundId < 0) {
                job.roundId = tr.roundId;
            } else if (job.roundId != tr.roundId) {
                throw std::runtime_error("Inconsistent roundId for jobId=" + std::to_string(tr.jobId));
            }
        }
        if (tr.groupId >= 0) {
            if (job.groupId < 0) {
                job.groupId = tr.groupId;
            } else if (job.groupId != tr.groupId) {
                throw std::runtime_error("Inconsistent groupId for jobId=" + std::to_string(tr.jobId));
            }
        }
        if (!tr.deps.empty()) {
            std::unordered_set<int> depSet(job.deps.begin(), job.deps.end());
            for (int dep : tr.deps) {
                depSet.insert(dep);
            }
            job.deps.assign(depSet.begin(), depSet.end());
            std::sort(job.deps.begin(), job.deps.end());
        }

        if (tr.bytes <= 1e-12) {
            continue;
        }
        if (tr.aggSrc < 0 || tr.aggSrc >= numAgg || tr.aggDst < 0 || tr.aggDst >= numAgg) {
            throw std::runtime_error("Traffic agg id out of range for flowId=" + std::to_string(tr.flowId));
        }

        Flow flow;
        flow.jobId = tr.jobId;
        flow.flowId = tr.flowId;
        flow.aggSrc = tr.aggSrc;
        flow.aggDst = tr.aggDst;
        flow.torSrc = aggParentTor[tr.aggSrc];
        flow.torDst = aggParentTor[tr.aggDst];
        flow.bytes = tr.bytes;
        flow.startTime = tr.startTime;
        job.flows.push_back(flow);
    }

    std::vector<Job> jobs;
    jobs.reserve(byJob.size());
    for (auto& kv : byJob) {
        auto& job = kv.second;
        for (int dep : job.deps) {
            if (dep == job.jobId) {
                throw std::runtime_error("Job dep cannot point to itself. jobId=" + std::to_string(job.jobId));
            }
        }
        std::sort(job.flows.begin(), job.flows.end(), [](const Flow& a, const Flow& b) {
            if (a.bytes != b.bytes) {
                return a.bytes > b.bytes;
            }
            return a.flowId < b.flowId;
        });
        jobs.push_back(std::move(job));
    }

    std::sort(jobs.begin(), jobs.end(), [](const Job& a, const Job& b) {
        if (a.startTime != b.startTime) {
            return a.startTime < b.startTime;
        }
        return a.jobId < b.jobId;
    });

    return jobs;
}

}  // namespace flsim
