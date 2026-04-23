#ifndef FLOW_LEVEL_SIM_TRAFFIC_READER_H
#define FLOW_LEVEL_SIM_TRAFFIC_READER_H

#include <string>
#include <vector>

#include "types.h"

namespace flsim {

enum class TrafficInputFormat {
    Auto = 0,
    Flow6 = 1,
    TraceDep6 = 2,
};

std::vector<TrafficEntry> readTrafficFile(const std::string& filename,
                                          TrafficInputFormat format = TrafficInputFormat::Auto);
std::vector<Job> buildJobsFromTraffic(const std::vector<TrafficEntry>& traffic,
                                      const std::vector<int>& aggParentTor);

}  // namespace flsim

#endif
