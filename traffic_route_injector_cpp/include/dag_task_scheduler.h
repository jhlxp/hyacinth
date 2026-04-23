#ifndef FLOW_LEVEL_SIM_DAG_TASK_SCHEDULER_H
#define FLOW_LEVEL_SIM_DAG_TASK_SCHEDULER_H

#include <cstddef>
#include <queue>
#include <unordered_map>
#include <vector>

#include "types.h"

namespace flsim {

class DagTaskScheduler {
public:
    struct ReadyNode {
        std::size_t index = 0;
        int jobId = -1;
        double readyTime = 0.0;
    };

    explicit DagTaskScheduler(const std::vector<Job>& jobs);

    bool empty() const;
    ReadyNode popReady();
    void markFinished(std::size_t index, double finishTime);

    int processedCount() const;
    int totalJobs() const;

private:
    struct ReadyCmp {
        bool operator()(const ReadyNode& a, const ReadyNode& b) const {
            if (a.readyTime != b.readyTime) {
                return a.readyTime > b.readyTime;
            }
            return a.jobId > b.jobId;
        }
    };

    const std::vector<Job>& jobs_;
    std::unordered_map<int, std::size_t> indexByJobId_;
    std::vector<int> indegree_;
    std::vector<std::vector<std::size_t>> successors_;
    std::vector<double> maxPredFinish_;
    std::vector<bool> finished_;
    std::priority_queue<ReadyNode, std::vector<ReadyNode>, ReadyCmp> readyQ_;
    int processed_ = 0;
};

}  // namespace flsim

#endif
