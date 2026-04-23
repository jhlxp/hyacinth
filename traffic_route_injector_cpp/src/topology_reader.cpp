#include "topology_reader.h"

#include <fstream>
#include <stdexcept>

namespace flsim {

TopologyInput readTopologyFile(const std::string& filename) {
    std::ifstream fin(filename);
    if (!fin.is_open()) {
        throw std::runtime_error("Cannot open topology file: " + filename);
    }

    TopologyInput topo;
    if (!(fin >> topo.H >> topo.dl >> topo.ul >> topo.ntorHdr >> topo.N)) {
        throw std::runtime_error("Failed to read topology header from: " + filename);
    }
    if (topo.N <= 0) {
        throw std::runtime_error("Invalid N in topology header.");
    }

    topo.adj.assign(topo.N, std::vector<int>(topo.N, 0));
    for (int i = 0; i < topo.N; ++i) {
        for (int j = 0; j < topo.N; ++j) {
            if (!(fin >> topo.adj[i][j])) {
                throw std::runtime_error("Failed to read adjacency matrix row " + std::to_string(i));
            }
            if (topo.adj[i][j] != 0 && topo.adj[i][j] != 1) {
                throw std::runtime_error("Adjacency matrix must contain only 0/1.");
            }
        }
    }
    return topo;
}

std::vector<int> inferAggParentTor(const std::vector<std::vector<int>>& fullAdj,
                                   int numTor,
                                   int numEps) {
    const int N = static_cast<int>(fullAdj.size());
    const int aggBase = numTor + numEps;
    const int numAgg = N - aggBase;
    if (numAgg < 0) {
        throw std::runtime_error("numAgg < 0, invalid numTor/numEps.");
    }

    std::vector<int> parent(numAgg, -1);
    for (int a = 0; a < numAgg; ++a) {
        const int globalAgg = aggBase + a;
        int cnt = 0;
        int p = -1;
        for (int tor = 0; tor < numTor; ++tor) {
            if (fullAdj[globalAgg][tor] == 1 || fullAdj[tor][globalAgg] == 1) {
                ++cnt;
                p = tor;
            }
        }
        if (cnt != 1) {
            throw std::runtime_error(
                "Agg " + std::to_string(a) +
                " must connect to exactly one ToR, but found " + std::to_string(cnt));
        }
        parent[a] = p;
    }
    return parent;
}

std::vector<std::vector<double>> buildCoreCapacityMatrix(const std::vector<std::vector<int>>& fullAdj,
                                                         int numTor,
                                                         int numEps,
                                                         double rateTorTor,
                                                         double rateTorEps) {
    const int coreN = numTor + numEps;
    std::vector<std::vector<double>> C(coreN, std::vector<double>(coreN, 0.0));

    for (int u = 0; u < coreN; ++u) {
        for (int v = 0; v < coreN; ++v) {
            if (u == v || fullAdj[u][v] == 0) {
                continue;
            }
            const bool uIsTor = (u < numTor);
            const bool vIsTor = (v < numTor);
            const bool uIsEps = (u >= numTor && u < coreN);
            const bool vIsEps = (v >= numTor && v < coreN);

            if (uIsTor && vIsTor) {
                C[u][v] = rateTorTor;
            } else if ((uIsTor && vIsEps) || (uIsEps && vIsTor)) {
                C[u][v] = rateTorEps;
            }
        }
    }
    return C;
}

}  // namespace flsim
