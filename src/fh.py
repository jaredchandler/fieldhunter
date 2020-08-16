"""
Only implements FH's binary message handling using n-grams (not textual using delimiters!)
"""

from argparse import ArgumentParser
from os.path import isfile, basename, splitext

from typing import Dict, Tuple, Iterable, Sequence, List
from itertools import groupby, product, chain, combinations
from collections import Counter
import random, numpy
from scipy.stats import pearsonr
from netzob.Model.Vocabulary.Messages.AbstractMessage import AbstractMessage

# noinspection PyUnresolvedReferences
from tabulate import tabulate
# noinspection PyUnresolvedReferences
from pprint import pprint
# noinspection PyUnresolvedReferences
import IPython

from nemere.utils.loader import SpecimenLoader
from nemere.inference.analyzers import Value
from nemere.inference.segments import TypedSegment
from fieldhunter.utils.base import Flows, list2ranges
from fieldhunter.inference.fieldtypes import *
from fieldhunter.utils.base import NgramIterator, entropyFilteredOffsets, iterateSelected, intsFromNgrams, ngramIsOverlapping


if __name__ == '__main__':
    parser = ArgumentParser(
        description='Re-Implementation of FieldHunter.')
    parser.add_argument('pcapfilename', help='Filename of the PCAP to load.')
    parser.add_argument('-i', '--interactive', help='open ipython prompt after finishing the analysis.',
                        action="store_true")
    args = parser.parse_args()

    if not isfile(args.pcapfilename):
        print('File not found: ' + args.pcapfilename)
        exit(1)
    pcapbasename = basename(args.pcapfilename)
    trace = splitext(pcapbasename)[0]
    # reportFolder = join(reportFolder, trace)
    # if not exists(reportFolder):
    #    makedirs(reportFolder)

    specimens = SpecimenLoader(args.pcapfilename)
    messages = list(specimens.messagePool.keys())  # type: List[L2NetworkMessage]
    flows = Flows(messages)

    # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # #
    # TODO reactivate finally

    # # MSG-type
    # msgtypefields = MSGtype(flows)
    # TODO The entropyThresh is not given in FH, so generate some statisics, illustrations,
    #   CDF, histograms, ... using our traces
    # print(tabulate(zip(msgtypefields.c2sEntropy, msgtypefields.s2cEntropy), headers=["c2s", "s2c"], showindex=True))

    # # MSG-len
    # msglenfields = MSGlen(flows)
    # print(tabulate(list(msglenfields.acceptedCandidatesPerDir[0].items()) + ["--"]
    #                + list(msglenfields.acceptedCandidatesPerDir[1].items())))

    # # Host-ID
    # hostidfields = HostID(messages)
    # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # #
    # # # # Investigate low categoricalCorrelation for all but one byte within an address field (see NTP and DHCP).
    # # # # According to NTP offset 12 (REF ID, often DST IP address) and DHCP offsets (12, 17, and) 20 (IPs)
    # # # # this works in principle, but if the n-gram is too short the correlation gets lost some n-grams.
    # # print(tabulate(zip(*[categoricalCorrelation]), showindex="always"))
    # # from matplotlib import pyplot
    # # pyplot.bar(range(len(categoricalCorrelation)), categoricalCorrelation)
    # # pyplot.show()
    # # # sum([msg.data[20:24] == bytes(map(int, msg.source.rpartition(':')[0].split('.'))) for msg in messages])
    # # # sum([int.from_bytes(messages[m].data[20:24], "big") == srcs[m] for m in range(len(messages))])
    # # # # While the whole bootp.ip.server [20:24] correlates nicely to the IP address, single n-grams don't.
    # # serverIP = [(int.from_bytes(messages[m].data[20:24], "big"), srcs[m]) for m in range(len(messages))]
    # # serverIP0 = [(messages[m].data[20], srcs[m]) for m in range(len(messages))]
    # # serverIP1 = [(messages[m].data[21], srcs[m]) for m in range(len(messages))]
    # # serverIP2 = [(messages[m].data[22], srcs[m]) for m in range(len(messages))]
    # # serverIP3 = [(messages[m].data[23], srcs[m]) for m in range(len(messages))]
    # # # nsp = numpy.array([sip for sip in serverIP])
    # # # # The correlation is perfect, if null values are omitted
    # # nsp = numpy.array([sip for sip in serverIP if sip[0] != 0])   #  and sip[0] == sip[1]
    # # # nsp0 = numpy.array(serverIP0)
    # # # nsp1 = numpy.array(serverIP1)
    # # # nsp2 = numpy.array(serverIP2)
    # # # nsp3 = numpy.array(serverIP3)
    # # nsp0 = numpy.array([sip for sip in serverIP0 if sip[0] != 0])
    # # nsp1 = numpy.array([sip for sip in serverIP1 if sip[0] != 0])
    # # nsp2 = numpy.array([sip for sip in serverIP2 if sip[0] != 0])
    # # nsp3 = numpy.array([sip for sip in serverIP3 if sip[0] != 0])
    # # for serverSrcPairs in [nsp, nsp0, nsp1, nsp2, nsp3]:
    # #     print(drv.information_mutual(serverSrcPairs[:, 0], serverSrcPairs[:, 1]) / drv.entropy_joint(serverSrcPairs.T))
    # # # # TODO This is no implementation error, but raises doubts about the Host-ID description completeness:
    # # # #  Probably it does not mention a Entropy filter, direction separation, or - most probably -
    # # # #  an iterative n-gram size
    # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # #
    # print(HostID.catCorrPosLen(hostidfields.categoricalCorrelation))

    # # Session-ID (FH, Section 3.2.4)
    # sessionidfields = SessionID(messages)
    # # Problem similar to Host-ID leads to same bad performance.
    # # Moreover, Host-ID will always return a subset of Session-ID fields, so Host-ID should get precedence.
    # print(HostID.catCorrPosLen(sessionidfields.categoricalCorrelation))

    pass
    # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # #
    # # # TODO Working area
    # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # #

    # TODO Trans-ID (FH, Section 3.2.5, Fig. 3 right)
    transSupportThresh = 0.8  # enough support in conversations (FH, Sec. 3.2.5)
    minFieldLength = 2  # merged n-grams must at least be this amount of bytes long
    # n-gram size is not explicitly given in FH, but the description (merging, sharp drops in entropy in Fig. 6)
    #   leads to assuming it should be 1.
    n = 1

    # "random across vertical and horizontal collections" (FH, Sec. 3.2.5)
    #   entropy in c2s/s2c + flows: threshold for high entropy is not given in FH! Use value determined
    #   by own empirics in base.entropyThresh

    # vertical collections
    c2s, s2c = flows.splitDirections()  # type: List[L4NetworkMessage], List[L4NetworkMessage]
    _c2sEntropyFiltered = entropyFilteredOffsets(c2s, 1)
    _s2cEntropyFiltered = entropyFilteredOffsets(s2c, 1)
    # print('_c2sEntropyFiltered')
    # pprint(_c2sEntropyFiltered)
    # print('_s2cEntropyFiltered')
    # pprint(_s2cEntropyFiltered)

    # horizontal collections: entropy of n-gram per the same offset in all messages of one flow direction
    _c2sConvsEntropy = dict()
    for key, conv in flows.c2sInConversations().items():
        _c2sConvsEntropy[key] = pyitNgramEntropy(conv, n)
    _s2cConvsEntropy = dict()
    for key, conv in flows.s2cInConversations().items():
        _s2cConvsEntropy[key] = pyitNgramEntropy(conv, n)
    # print('_c2sConvsEntropy')
    # pprint(_c2sConvsEntropy)
    # print('_s2cConvsEntropy')
    # pprint(_s2cConvsEntropy)

    _c2sConvsEntropyFiltered = dict()
    for key, conv in flows.c2sInConversations().items():
        # The entropy is too low if the number of specimens is low -> relative to max
        #  and ignore conversations of length 1 (TODO probably even more? "Transaction ID" in DHCP is a FP, since it is actually a Session-ID)
        if len(conv) <= 1:
            continue
        _c2sConvsEntropyFiltered[key] = entropyFilteredOffsets(conv, 1, False)
    _s2cConvsEntropyFiltered = dict()
    for key, conv in flows.s2cInConversations().items():
        # The entropy is too low if the number of specimens is low -> relative to max
        #  and ignore conversations of length 1 (TODO probably even more? "Transaction ID" in DHCP is a FP, since it is actually a Session-ID)
        if len(conv) <= 1:
            continue
        _s2cConvsEntropyFiltered[key] = entropyFilteredOffsets(conv, 1, False)
    # print('_c2sConvsEntropyFiltered')
    # pprint(_c2sConvsEntropyFiltered)
    # print('_s2cConvsEntropyFiltered')
    # pprint(_s2cConvsEntropyFiltered)

    # req./resp. pairs: search for n-grams with constant values (differing offsets allowed)
    #
    # intersection of all c2s and s2c filtered offset lists (per flow)
    _c2sHorizontalOffsets = set.intersection(*[set(offsetlist) for offsetlist in _c2sConvsEntropyFiltered.values()])
    _s2cHorizontalOffsets = set.intersection(*[set(offsetlist) for offsetlist in _s2cConvsEntropyFiltered.values()])
    # offsets in _c2sEntropyFiltered where the offset is also in all of the lists of _c2sConvsEntropyFiltered
    # (TODO use entry for this query specifically?)
    _c2sCombinedOffsets = _c2sHorizontalOffsets.intersection(_c2sEntropyFiltered)
    # offsets in _c2sEntropyFiltered where the offset is also in all of the lists of _s2cConvsEntropyFiltered
    # (TODO the entry for this resp specifically?)
    _s2cCombinedOffsets = _s2cHorizontalOffsets.intersection(_s2cEntropyFiltered)
    # compute Q->R association
    mqr = flows.matchQueryRespone()
    # from the n-gram offsets that passed the entropy-filters determine those that have the same value in mqr pairs
    valuematch = dict()
    for query, resp in mqr.items():
        qrmatchlist = valuematch[(query, resp)] = list()
        # value in query at any of the offsets in _c2sCombinedOffsets
        for c2sOffset in _c2sCombinedOffsets:
            if len(query.data) < c2sOffset + n:
                continue
            qvalue = query.data[c2sOffset:c2sOffset + n]
            # matches a value of resp at any of the offsets in _s2cCombinedOffsets
            for s2cOffset in _s2cCombinedOffsets:
                if len(resp.data) < s2cOffset + n:
                    continue
                rvalue = resp.data[s2cOffset:s2cOffset + n]
                if qvalue == rvalue:
                    qrmatchlist.append((c2sOffset, s2cOffset))

    # measure consistency: offsets recognized in more than transSupportThresh of conversations
    c2sCandidateCount = Counter()
    s2cCandidateCount = Counter()
    for (query, resp), offsetlist in valuematch.items():
        if len(offsetlist) < 1:
            continue
        # transpose to offsets per direction
        c2sOffsets, s2cOffsets = zip(*offsetlist)
        c2sCandidateCount.update(set(c2sOffsets))
        s2cCandidateCount.update(set(s2cOffsets))
    c2sConsistentCandidates = [offset for offset, cc in c2sCandidateCount.items() if cc > transSupportThresh * len(c2s)]
    s2cConsistentCandidates = [offset for offset, cc in s2cCandidateCount.items() if cc > transSupportThresh * len(s2c)]

    # merge and filter candidates by minimum length
    c2sConsistentRanges = [ol for ol in list2ranges(c2sConsistentCandidates) if ol[1] + 1 >= minFieldLength]
    s2cConsistentRanges = [ol for ol in list2ranges(s2cConsistentCandidates) if ol[1] + 1 >= minFieldLength]

    # TODO place in own class and generate segments



    # TODO Accumulators (FH, Section 3.2.6)
    #   "Accumulators are fields that have increasing values over consecutive message within the same conversation." (FH, Sec. 3.2.6)

    # c2s and s2c independently
    # iterate n-grams' n = 8, 4, 3, 2
    # combined from Sec. 3.1.2: n=32, 24, 16 bits (4, 3, 2 bytes) and see Sec. 3.2.6: n=64, 32, 16 bits (8, 4, 2 bytes)

    # calculate delta between n-grams (n and offset identical) two subsequent messages
    # "compress": ln delta
    # "fairly constant": relatively low entropy -> threshold (value not given)
    # check: delta positive and fairly constant

    # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # #
    # TODO for validation, sub-class nemere.validation.messageParser.ParsingConstantsXXX
    #   set TYPELOOKUP[x] to the value FieldType.typelabel (e. g., "MSG-Type") for all fields in
    #   nemere.validation.messageParser.MessageTypeIdentifiers

    # interactive
    IPython.embed()

