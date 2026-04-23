#!/bin/bash

###########################################################
#  Concurrency-limited launcher (max 8 background jobs)
###########################################################
MAXJOBS=24

run_with_limit() {
    # Wait until number of running jobs < MAXJOBS
    while [ "$(jobs -rp | wc -l)" -ge "$MAXJOBS" ]; do
        sleep 0.5
    done

    "$@" &
}

###########################################################
# Base directory to store generated HTSIM flow files
###########################################################
BASE_DIR="../tasks/datamining_traffic"

WORKLOAD="./flow_distr/datamining.csv"

###########################################################
# Global offered loads (shared across all topologies)
###########################################################
LOADS=(0.3 0.4 0.5 0.6)

###########################################################
# Per-topology configuration of (RACKS, CVALUES)
# Each topology can have its own list.
# RACKS[i] corresponds to CVALUES[i].
###########################################################
declare -A RACKS_MAP
declare -A CVALUES_MAP
declare -A NICS_MAP

# ---- Expander ----
RACKS_MAP[expander]="128 320"
CVALUES_MAP[expander]="8 8"

# ---- DC ----
RACKS_MAP[dc]="128 320"
CVALUES_MAP[dc]="8 8"

# ---- Dragonfly ----
RACKS_MAP[dragonfly]="264 510"
CVALUES_MAP[dragonfly]="4 5"

# ---- Torus ----
RACKS_MAP[torus]="256 648"
CVALUES_MAP[torus]="4 4"

# ---- Clos ----
RACKS_MAP[clos]="105 180"
CVALUES_MAP[clos]="10 14"

# ---- Zcube ----
RACKS_MAP[zcube]="1000 2744"
CVALUES_MAP[zcube]="1 1"

# ---- nics ---
NICS_MAP[expander]="1"
NICS_MAP[dc]="1"
NICS_MAP[dragonfly]="1"
NICS_MAP[torus]="1"
NICS_MAP[clos]="1"
NICS_MAP[zcube]="3"

###########################################################
# Main execution loop
###########################################################
for TOPO in "${!RACKS_MAP[@]}"; do
    OUTDIR="${BASE_DIR}/${TOPO}"
    mkdir -p "$OUTDIR"

    echo "========== Running topology: $TOPO =========="

    RLIST=(${RACKS_MAP[$TOPO]})
    CLIST=(${CVALUES_MAP[$TOPO]})
    NICS=${NICS_MAP[$TOPO]}

    # Safety: (R, C) must match
    if [ ${#RLIST[@]} -ne ${#CLIST[@]} ]; then
        echo "ERROR: RACKS and CVALUES length mismatch for topology '$TOPO'"
        exit 1
    fi

    # Iterate through (R, C)
    for ((i=0; i<${#RLIST[@]}; i++)); do
        R=${RLIST[$i]}
        C=${CLIST[$i]}

        # Iterate through load levels
        for L in "${LOADS[@]}"; do
            echo " [QUEUE] topo=$TOPO, racks=$R, c=$C, load=$L"

            run_with_limit python3 generate_traffic.py \
                -t $TOPO \
                -r $R \
                -c $C \
                -l $L \
                -T 2.001 \
                --nics $NICS \
                --nic-rate 100e9 \
                --outdir "$OUTDIR" \
                --workload "$WORKLOAD"
        done
    done
done

###########################################################
# Wait for all tasks to finish
###########################################################
wait
echo "All traffic generation tasks finished! (Max concurrency = $MAXJOBS)"
