#include "dag_task_scheduler.h"

#include <algorithm>
#include <stdexcept>

namespace flsim {

DagTaskScheduler::DagTaskScheduler(const std::vector<Job>& jobs)
    : jobs_(jobs),
      indegree_(jobs.size(), 0),
      successors_(jobs.size()),
      maxPredFinish_(jobs.size(), 0.0),
      finished_(jobs.size(), false) {
    indexByJobId_.reserve(jobs_.size());
    for (std::size_t i = 0; i < jobs_.size(); ++i) {
        const auto insert = indexByJobId_.emplace(jobs_[i].jobId, i);
        if (!insert.second) {
            throw std::runtime_error("Duplicated jobId in DAG scheduler input: " +
                                     std::to_string(jobs_[i].jobId));
        }
    }

    for (std::size_t i = 0; i < jobs_.size(); ++i) {
        const auto& job = jobs_[i];
        for (int depJobId : job.deps) {
            const auto it = indexByJobId_.find(depJobId);
            if (it == indexByJobId_.end()) {
                throw std::runtime_error("Unknown dep jobId=" + std::to_string(depJobId) +
                                         " referenced by jobId=" + std::to_string(job.jobId));
            }
            const std::size_t depIdx = it->second;
            successors_[depIdx].push_back(i);
            ++indegree_[i];
        }
    }

    for (std::size_t i = 0; i < jobs_.size(); ++i) {
        if (indegree_[i] == 0) {
            readyQ_.push(ReadyNode{i, jobs_[i].jobId, jobs_[i].startTime});
        }
    }

    if (jobs_.empty()) {
        return;
    }
    if (readyQ_.empty()) {
        throw std::runtime_error("No initial ready job found. Dependency graph may contain a cycle.");
    }
}

bool DagTaskScheduler::empty() const {
    return readyQ_.empty();
}

DagTaskScheduler::ReadyNode DagTaskScheduler::popReady() {
    if (readyQ_.empty()) {
        throw std::runtime_error("DAG ready queue is empty.");
    }
    ReadyNode node = readyQ_.top();
    readyQ_.pop();
    if (node.index >= jobs_.size()) {
        throw std::runtime_error("DAG ready node index out of range.");
    }
    return node;
}

void DagTaskScheduler::markFinished(std::size_t index, double finishTime) {
    if (index >= jobs_.size()) {
        throw std::runtime_error("markFinished index out of range.");
    }
    if (finished_[index]) {
        return;
    }
    finished_[index] = true;
    ++processed_;

    for (std::size_t succIdx : successors_[index]) {
        maxPredFinish_[succIdx] = std::max(maxPredFinish_[succIdx], finishTime);
        --indegree_[succIdx];
        if (indegree_[succIdx] == 0) {
            const double readyTime = std::max(jobs_[succIdx].startTime, maxPredFinish_[succIdx]);
            readyQ_.push(ReadyNode{succIdx, jobs_[succIdx].jobId, readyTime});
        }
    }
}

int DagTaskScheduler::processedCount() const {
    return processed_;
}

int DagTaskScheduler::totalJobs() const {
    return static_cast<int>(jobs_.size());
}

}  // namespace flsim
