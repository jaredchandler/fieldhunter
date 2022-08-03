"""
Only implements FH's binary message handling using n-grams (not textual using delimiters!)
"""

from argparse import ArgumentParser
from time import time

# noinspection PyUnresolvedReferences
from tabulate import tabulate
# noinspection PyUnresolvedReferences
from pprint import pprint
# noinspection PyUnresolvedReferences
import IPython

from nemere.utils.loader import SpecimenLoader
from nemere.utils.evaluationHelpers import StartupFilecheck
from nemere.utils.reportWriter import writeReport
from nemere.validation.dissectorMatcher import MessageComparator, DissectorMatcher

from fieldhunter.inference.fieldtypes import *
from fieldhunter.inference.common import segmentedMessagesAndSymbols
from fieldhunter.utils.base import Flows
from fieldhunter.utils.eval import FieldTypeReport




if __name__ == '__main__':
    parser = ArgumentParser(
        description='Re-Implementation of FieldHunter.')
    parser.add_argument('pcapfilename', help='Filename of the PCAP to load.')
    parser.add_argument('-i', '--interactive', help='open ipython prompt after finishing the analysis.',
                        action="store_true")
    # Pointless options: FH requires TCP/UDP over IP (FH, Section 6.6)
    # parser.add_argument('-l', '--layer', type=int, default=2,
    #                     help='Protocol layer relative to IP to consider. Default is 2 layers above IP '
    #                          '(typically the payload of a transport protocol).')
    # parser.add_argument('-r', '--relativeToIP', default=True, action='store_false')
    args = parser.parse_args()
    layer = 2
    relativeToIP = True

    filechecker = StartupFilecheck(args.pcapfilename)

    specimens = SpecimenLoader(args.pcapfilename, layer = layer, relativeToIP = relativeToIP)
    # noinspection PyTypeChecker
    messages = list(specimens.messagePool.keys())  # type: List[L4NetworkMessage]
    flows = Flows(messages)

    # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # #
    print("Hunting fields in", filechecker.pcapstrippedname)
    inferenceStart = time()

    # MSG-type
    print("Inferring", MSGtype.typelabel)
    msgtypefields = MSGtype(flows)

    # MSG-len
    print("Inferring", MSGlen.typelabel)
    msglenfields = MSGlen(flows)

    # Host-ID
    print("Inferring", HostID.typelabel)
    hostidfields = HostID(messages)

    # Session-ID (FH, Section 3.2.4)
    print("Inferring", SessionID.typelabel)
    sessionidfields = SessionID(messages)

    # Trans-ID (FH, Section 3.2.5)
    print("Inferring", TransID.typelabel)
    transidfields = TransID(flows)

    # Accumulators (FH, Section 3.2.6)
    print("Inferring", Accumulator.typelabel)
    accumulatorfields = Accumulator(flows)

    # in order of fieldtypes.precedence!
    sortedInferredTypes = sorted(
        (msglenfields, msgtypefields, hostidfields, sessionidfields, transidfields, accumulatorfields),
        key=lambda l: precedence[l.typelabel] )
    segmentedMessages, symbols = segmentedMessagesAndSymbols(sortedInferredTypes, messages)
    print("HARNESSSTART")
    for s in symbols[:int(len(symbols)/2)]:
      print(" ".join([v.hex() for v in s.getCells()[0]]))
    print("HARNESSEND")
    quit()
    inferenceDuration = time() - inferenceStart
    # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # #
    # statistics for all types
    print(tabulate(
        [(infield.typelabel,
            sum(1 for msgsegs in infield.segments if len(msgsegs) > 0),
            max(len(msgsegs) for msgsegs in infield.segments)
                if len(infield.segments) > 0 else 0 # prevent empty sequence for max()
        ) for infield in sortedInferredTypes],
        headers=["typelabel","messages","max inferred per msg"]
    ))

    # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # #

    nontrivialSymbols = [sym for sym in symbols if len(sym.fields) > 1]
    comparator = MessageComparator(specimens, layer=layer, relativeToIP=relativeToIP)
    print("Dissection complete.")
    comparator.pprintInterleaved(nontrivialSymbols)
    print(f"\n   + {len(symbols)-len(nontrivialSymbols)} messages without any inferred fields.")

    # calc FMS per message
    print("Calculate FMS...")
    message2quality = DissectorMatcher.symbolListFMS(comparator, symbols)
    # write statistics to csv
    writeReport(message2quality, inferenceDuration, comparator, "fieldhunter-literal",
                filechecker.reportFullPath)

    # FTR validation: calculate TP/FP/FN ==> P/R per protocol and per type
    infieldWorkbook = FieldTypeReport.newWorkbook()
    for infields in sortedInferredTypes:
        infieldReport = FieldTypeReport(infields, comparator, segmentedMessages)
        infieldReport.addXLworksheet(infieldWorkbook, FieldTypeReport.ovTitle)
    FieldTypeReport.saveWorkbook(infieldWorkbook, filechecker.pcapstrippedname)

    # interactive
    if args.interactive:
        IPython.embed()

