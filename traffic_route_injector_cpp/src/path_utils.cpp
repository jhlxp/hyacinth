#include "path_utils.h"

#include <algorithm>
#include <queue>
#include <set>
#include <stdexcept>

namespace flsim {

std::vector<CandidatePath> enumerateCandidatePaths(int s,
                                                   int t,
                                                   const std::vector<std::vector<double>>& C,
                                                   int numTor,
                                                   int numEps) {
    std::vector<CandidatePath> out;

    auto addPath = [&](const std::vector<int>& p) {
        for (const auto& q : out) {
            if (q.nodes == p) {
                return;
            }
        }
        out.push_back({p});
    };

    if (C[s][t] > 1e-9) {
        addPath({s, t});
    }

    for (int k = 0; k < numTor; ++k) {
        if (k == s || k == t) {
            continue;
        }
        if (C[s][k] > 1e-9 && C[k][t] > 1e-9) {
            addPath({s, k, t});
        }
    }

    for (int k1 = 0; k1 < numTor; ++k1) {
        if (k1 == s || k1 == t || C[s][k1] <= 1e-9) {
            continue;
        }
        for (int k2 = 0; k2 < numTor; ++k2) {
            if (k2 == s || k2 == t || k2 == k1) {
                continue;
            }
            if (C[k1][k2] > 1e-9 && C[k2][t] > 1e-9) {
                addPath({s, k1, k2, t});
            }
        }
    }

    for (int e = numTor; e < numTor + numEps; ++e) {
        if (C[s][e] > 1e-9 && C[e][t] > 1e-9) {
            addPath({s, e, t});
        }
    }

    for (int k = 0; k < numTor; ++k) {
        if (k == s || k == t || C[s][k] <= 1e-9) {
            continue;
        }
        for (int e = numTor; e < numTor + numEps; ++e) {
            if (C[k][e] > 1e-9 && C[e][t] > 1e-9) {
                addPath({s, k, e, t});
            }
        }
    }

    for (int e = numTor; e < numTor + numEps; ++e) {
        if (C[s][e] <= 1e-9) {
            continue;
        }
        for (int k = 0; k < numTor; ++k) {
            if (k == s || k == t) {
                continue;
            }
            if (C[e][k] > 1e-9 && C[k][t] > 1e-9) {
                addPath({s, e, k, t});
            }
        }
    }

    return out;
}

std::vector<Edge> pathToEdges(const CandidatePath& p) {
    std::vector<Edge> edges;
    for (int i = 0; i + 1 < static_cast<int>(p.nodes.size()); ++i) {
        edges.push_back({p.nodes[i], p.nodes[i + 1]});
    }
    return edges;
}

double pathBottleneckRate(const CandidatePath& p, const std::vector<std::vector<double>>& C) {
    double rate = 0.0;
    bool init = false;
    for (const auto& edge : pathToEdges(p)) {
        const double cap = C[edge.first][edge.second];
        if (cap <= 0.0) {
            throw std::runtime_error("Invalid candidate path edge with zero capacity.");
        }
        if (!init) {
            rate = cap;
            init = true;
        } else if (cap < rate) {
            rate = cap;
        }
    }
    return init ? rate : 0.0;
}

namespace {

std::vector<int> shortestPathBfsRestricted(int s,
                                           int t,
                                           const std::vector<std::vector<double>>& C,
                                           int maxNodeExclusive,
                                           const std::set<Edge>& bannedEdges,
                                           const std::set<int>& bannedNodes) {
    if (s < 0 || t < 0 || s >= maxNodeExclusive || t >= maxNodeExclusive) {
        return {};
    }
    if (bannedNodes.count(s) || bannedNodes.count(t)) {
        return {};
    }

    std::vector<int> parent(maxNodeExclusive, -1);
    std::vector<int> vis(maxNodeExclusive, 0);
    std::queue<int> q;
    vis[s] = 1;
    q.push(s);

    while (!q.empty()) {
        const int u = q.front();
        q.pop();
        if (u == t) {
            break;
        }
        for (int v = 0; v < maxNodeExclusive; ++v) {
            if (C[u][v] <= 1e-9 || vis[v] || bannedNodes.count(v) || bannedEdges.count({u, v})) {
                continue;
            }
            vis[v] = 1;
            parent[v] = u;
            q.push(v);
        }
    }

    if (!vis[t]) {
        return {};
    }
    std::vector<int> path;
    for (int cur = t; cur != -1; cur = parent[cur]) {
        path.push_back(cur);
    }
    std::reverse(path.begin(), path.end());
    return path;
}

}  // namespace

std::vector<CandidatePath> enumerateKShortestPaths(int s,
                                                   int t,
                                                   const std::vector<std::vector<double>>& C,
                                                   int K,
                                                   int maxNodeExclusive) {
    if (K <= 0) {
        return {};
    }
    std::vector<CandidatePath> A;
    std::vector<std::vector<int>> B;

    const auto firstPath = shortestPathBfsRestricted(s, t, C, maxNodeExclusive, {}, {});
    if (firstPath.empty()) {
        return {};
    }
    A.push_back({firstPath});

    auto existsInA = [&](const std::vector<int>& p) {
        for (const auto& cp : A) {
            if (cp.nodes == p) {
                return true;
            }
        }
        return false;
    };
    auto existsInB = [&](const std::vector<int>& p) {
        for (const auto& q : B) {
            if (q == p) {
                return true;
            }
        }
        return false;
    };

    for (int kth = 1; kth < K; ++kth) {
        const std::vector<int>& prevPath = A[kth - 1].nodes;
        for (int i = 0; i + 1 < static_cast<int>(prevPath.size()); ++i) {
            std::vector<int> rootPath(prevPath.begin(), prevPath.begin() + i + 1);
            const int spurNode = rootPath.back();

            std::set<Edge> bannedEdges;
            std::set<int> bannedNodes;
            for (const auto& p : A) {
                if (static_cast<int>(p.nodes.size()) > i &&
                    std::equal(rootPath.begin(), rootPath.end(), p.nodes.begin())) {
                    bannedEdges.insert({p.nodes[i], p.nodes[i + 1]});
                }
            }
            for (int j = 0; j + 1 < static_cast<int>(rootPath.size()); ++j) {
                bannedNodes.insert(rootPath[j]);
            }

            const auto spurPath =
                shortestPathBfsRestricted(spurNode, t, C, maxNodeExclusive, bannedEdges, bannedNodes);
            if (spurPath.empty()) {
                continue;
            }
            std::vector<int> totalPath = rootPath;
            totalPath.pop_back();
            totalPath.insert(totalPath.end(), spurPath.begin(), spurPath.end());
            if (!existsInA(totalPath) && !existsInB(totalPath)) {
                B.push_back(totalPath);
            }
        }

        if (B.empty()) {
            break;
        }
        std::stable_sort(B.begin(), B.end(), [](const std::vector<int>& a, const std::vector<int>& b) {
            if (a.size() != b.size()) {
                return a.size() < b.size();
            }
            return a < b;
        });
        A.push_back({B.front()});
        B.erase(B.begin());
    }
    return A;
}

std::vector<CandidatePath> enumeratePrunedOcsPaths(int s,
                                                   int t,
                                                   const std::vector<std::vector<double>>& C,
                                                   int numTor,
                                                   int maxHops,
                                                   int maxCandidates,
                                                   bool forceDirectIfAvailable) {
    std::vector<CandidatePath> out;
    auto addPath = [&](const std::vector<int>& p) {
        for (const auto& q : out) {
            if (q.nodes == p) {
                return;
            }
        }
        out.push_back({p});
    };

    if (s < 0 || t < 0 || s >= numTor || t >= numTor || maxHops <= 0 || maxCandidates <= 0) {
        return out;
    }

    if (C[s][t] > 1e-9) {
        addPath({s, t});
        if (forceDirectIfAvailable) {
            return out;
        }
    }

    std::vector<int> path = {s};
    std::vector<int> vis(numTor, 0);
    vis[s] = 1;

    std::function<void(int, int)> dfs = [&](int u, int depth) {
        if (static_cast<int>(out.size()) >= maxCandidates || depth >= maxHops) {
            return;
        }
        if (u == t) {
            addPath(path);
            return;
        }

        if (C[u][t] > 1e-9 && !vis[t]) {
            path.push_back(t);
            addPath(path);
            path.pop_back();
            if (static_cast<int>(out.size()) >= maxCandidates) {
                return;
            }
        }

        for (int v = 0; v < numTor; ++v) {
            if (v == t || vis[v] || C[u][v] <= 1e-9) {
                continue;
            }
            path.push_back(v);
            vis[v] = 1;
            dfs(v, depth + 1);
            vis[v] = 0;
            path.pop_back();
            if (static_cast<int>(out.size()) >= maxCandidates) {
                return;
            }
        }
    };

    dfs(s, 0);
    std::sort(out.begin(), out.end(), [](const CandidatePath& a, const CandidatePath& b) {
        if (a.nodes.size() != b.nodes.size()) {
            return a.nodes.size() < b.nodes.size();
        }
        return a.nodes < b.nodes;
    });
    if (static_cast<int>(out.size()) > maxCandidates) {
        out.resize(maxCandidates);
    }
    return out;
}

std::vector<CandidatePath> enumerateSingleHopEpsPaths(int s,
                                                      int t,
                                                      const std::vector<std::vector<double>>& C,
                                                      int numTor,
                                                      int numEps) {
    std::vector<CandidatePath> out;
    for (int e = numTor; e < numTor + numEps; ++e) {
        if (C[s][e] > 1e-9 && C[e][t] > 1e-9) {
            out.push_back({{s, e, t}});
        }
    }
    return out;
}

}  // namespace flsim
