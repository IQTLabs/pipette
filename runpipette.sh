#!/bin/bash

source ./pipetteconf.sh

function show_help()
{
    echo "pipette coprocessor setup (uses sudo)

    Usage: runpipette [option]
    Options:
      -c,  coproint      interface to send coprocessed traffic to
      -f,  fakeint       interface created for fake services to run on
      -m,  fakemac       fake mac for fake interface
      -i,  fakeips       fake ip for fake services, space delimitted (will be proxied from real IPS)
      -h,  help          print this help
      -b,  bridge        name of ovs bridge to create
      -p,  port          pipette port
      -v,  vlans         coprocessor vlans, space delimitted
      -r,  record        record traffic captured by pipette should be followed by location then size of file i.e.: -r /pcaps.file.pcap 50
      -n,  no-docker     run the ryu-manager on the local server instead of in a docker container"
}

function check_args()
{
    NO_DOCKER=0
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
            -m|fakemac)
                FAKESERVERMAC="$2"
                shift
                ;;
            -i|fakeips)
                NFVIPS=""
                while [[ "$2" != -* && -n "$2" ]]
                do
                  NFVIPS+="$2"
                  if [[ "$3" != -* && -n "$3" ]]; then
                    NFVIPS+=" "
                  fi
                  shift
                done 
                ;;
            -v|vlans)
                VLANS=""
                while [[ "$2" != -* && -n "$2" ]]
                do
                  VLANS+="$2"
                  if [[ "$3" != -* && -n "$3" ]]; then
                    NFVIPS+=" "
                  fi
                  shift
                done 
                ;;
            -b|bridge)
                BR="$2"
                shift
                ;;
            -p|port)
                OF="$2"
                shift
                ;;
            -r|record)
                RECORD=1
                PCAP_LOCATION="$2"
                shift
                FILE_SIZE="$2"
                shift
                ;;
            -n|no-docker)
                NO_DOCKER=1
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


if [ ! -d "$PIPETTE_TEMP_DIR" ]; then
  mkdir "$PIPETTE_TEMP_DIR"
fi

export BR VLANS COPROINT FAKEINT COPROPORT FAKEPORT FAKESERVERMAC NFVIPS
./configureovs.sh || exit 1

if [ $RECORD -ne 0 ]; then
    echo "Starting tcpdump on interface $COPROINT"
    sudo tcpdump -i "$COPROINT" -w "$PCAP_LOCATION" -C "$FILE_SIZE" -Z root &
    echo $! >> "$PIPETTE_TEMP_DIR/tcpdump"
fi

if [[ NO_DOCKER -ne 0 ]]; then
  ryu-manager --verbose --ofp-tcp-listen-port "$OF" pipette.py &
  echo $! >> "$PIPETTE_TEMP_DIR/ryu"
else
  docker build -f $DFILE . -t iqtlabs/pipette
  docker_id=$(docker run -d -e NFVIPS="$NFVIPS" -e FAKESERVERMAC="$FAKESERVERMAC" -e FAKECLIENTMAC="$FAKECLIENTMAC" -e VLANS="$VLANS" \
   -p 127.0.0.1:$OF:6653 -ti iqtlabs/pipette)
  echo "$docker_id" >> "$PIPETTE_TEMP_DIR/ryu.docker"
fi
