#!/bin/bash

source ./pipetteconf.sh

function show_help()
{
    echo "pipette coprocessor shutdown (uses sudo)

    Usage: shutdownpipette [option]
    Options:
      -c,  coproint      interface to send coprocessed traffic to
      -f,  fakeint       interface created for fake services to run on
      -h,  help          print this help
      -b,  bridge        name of ovs bridge to create"
}

function check_args()
{
    while [ $# -gt 1 ]; do
        case $1 in
            -c|coproint)
                COPROINT="$2"
                shift
                ;;
            -f|fakeint)
                FAKEINT="$2"
                shift
                ;;
            -b|bridge)
                BR="$2"
                shift
                ;;
            -h|\?|help)
                show_help
                exit
                ;;
        esac
        shift
    done
}

if [ $# -gt 0 ]; then
    check_args "$@"
fi

#sudo docker stop pipette
sudo kill -9 ryu-manager

#delete bridge
sudo ovs-vsctl del-br "$BR"

#bring down fake ip
sudo ip link set "ovs$FAKEINT" down

#remove fake switch
sudo ip link del dev "ovs$FAKEINT"

#reset coprocessor interface
sudo ip link set "$COPROINT" down
sudo ip link set "$COPROINT" up
