# interface connected to FAUCET coprocessor port.
COPROINT=enp0s3
# interface that will be created for fake services to run on.
FAKEINT=fake0
# OVS bridge name
BR=copro0

unction show_help()
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
else # print help
    show_help
    exit
fi


# stop pipette.
sudo pkill -9 ryu-manager

#delete bridge
sudo ovs-vsctl del-br $BR 

#bring down fake ip
sudo ifconfig ovs$FAKEINT down

#remove fake switch
sudo ip link del dev ovs$FAKEINT

#reset coprocessor interface
sudo ifconfig $COPROINT down
sudo ifconfig $COPROINT up
