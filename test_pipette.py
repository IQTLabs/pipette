#!/usr/bin/env python

import unittest
from ryu.controller import dpset
from ryu.controller.ofp_event import EventOFPMsgBase
from pipette import Pipette


class PipetteSmokeTest(unittest.TestCase):  # pytype: disable=module-attr
    """Test bare instantiation of controller classes."""

    def test_smoke(self):
        ryu_app = Pipette(dpset={})


if __name__ == "__main__":
    unittest.main()  # pytype: disable=module-attr
