# interface connected to FAUCET coprocessor port.
COPROINT=enx0023565c8859
# address fake services will be run on (will be proxied from real IPs)
# must have the same prefix width as real network.
NFVIP=10.10.0.1/16
# FAUCET VLAN where fake services will appear.
VLAN=2
# interface that will be created for fake services to run on.
FAKEINT=fake0
DFILE=Dockerfile.pi

##
# Optional config
##

# Reserved MAC addresses for fake services to use to talk to clients.
FAKESERVERMAC=0e:00:00:00:00:66
FAKECLIENTMAC=0e:00:00:00:00:67
# OVS bridge name
BR=copro0
# pipette OF port
OF=6699
