"""
Infer message field types according to the FieldHunter paper Section 3.2
but with some relaxed thresholds and assumptions.

TODO introduce doctests to check critical functions in inference.fieldtypes
"""
from typing import List, Tuple, Dict, Iterable, ItemsView, Union
import random, logging
from itertools import groupby, product, chain, combinations, zip_longest
from collections import Counter
from abc import ABC, abstractmethod

import numpy
from scipy.stats import pearsonr
from pyitlib import discrete_random_variable as drv
from netzob.Model.Vocabulary.Messages.AbstractMessage import AbstractMessage
from netzob.Model.Vocabulary.Messages.L2NetworkMessage import L2NetworkMessage
from netzob.Model.Vocabulary.Messages.L4NetworkMessage import L4NetworkMessage

from nemere.inference.segments import TypedSegment

from fieldhunter.utils.base import qrAssociationCorrelation, verticalByteMerge, mutualInformationNormalized, \
    list2ranges, Flows, NgramIterator, iterateSelected, intsFromNgrams, \
    ngramIsOverlapping, pyitNgramEntropy
from fieldhunter.inference.fieldtypes import NonConstantNonRandomEntropyFieldType, FieldType, Accumulator
import fieldhunter.inference.fieldtypes as fieldtypes


logging.getLogger(__name__).setLevel(logging.DEBUG)


class MSGtype(fieldtypes.MSGtype):
    """
    Relaxed version of message type (MSG-Type) inference (FH, Section 3.2.1, Fig. 3 left).

    see .fieldtypes.MSGtype
    """
    causalityThresh = 0.7
    """
    FH, Sec. 3.2.1 says 0.8, but that leaves no candidates for our NTP traces
    Reduces TP and FP for SMB 100.
    """


class MSGlen(fieldtypes.MSGlen):
    """
    Relaxed version of message length (MSG-Len) inference (FH, Section 3.2.2, Fig. 3 center).

    see .fieldtypes.MSGlen
    """
    # coefficient threshold 0.6 (FH, Section 3.2.2)
    minCorrelation = 0.6
    # MSG-Len hypothesis threshold 0.9 (FH, Section 3.2.2)
    lenhypoThresh = 0.9

    def __init__(self, flows: Flows):
        super(NonConstantNonRandomEntropyFieldType, self).__init__()

        # The FH paper per direction wants to handle each direction separately, which is pointless for MSG-Len,
        # so we place all messages in one direction object.
        self._msgDirection = [type(self).Direction(flows.messages)]
        # TODO It might rather be useful to separate message types (distinct formats) in this manner.
        #   However, this requires combination with some message type classification approach. => Future Work.

    class Direction(fieldtypes.MSGlen.Direction):

        @staticmethod
        def _candidateIsAcceptable(solutionAcceptable: Dict[Tuple[AbstractMessage, AbstractMessage], bool],
                                   Xarray: numpy.ndarray):
            """
            FH does not require that either the values in X[0]/a or X[1]/b are equal for all X in Xes.
            Thus, different values are accepted, although a message length typically is calculated using the same
            multiplicator X[0], even if the offset X[1] may change, so X[0] must be a scalar value.

            Otherwise we end up with lots of FPs. Examples:
                * In SMB, the 'Msg. Len. Model Parameters' (a,b) == [1., 4.]
                  of the 4-gram at offset 0, 4 is nbss.length, i. e., a TP!
                  Offsets 16 and 22 are FP, but with diverging A and B vectors.
                * Another example: In DNS, the beginning of the queried name is a FP
                  (probably due to DNS' subdomain numbered separator scheme).

            Thus, we require that X[0] is the same constant value throughout the majority of checked solutions.
            (We use the majority to account for some random error exactly as FH does using the MSGlen.lenhypoThresh)

            :param solutionAcceptable: Dict of which solution is acceptable for which combination of messages.
            :return: Whether the given candidate is acceptable.
            """
            acceptCount = Counter(solutionAcceptable.values())
            mostlyAcceptable = bool(acceptCount[True] / len(acceptCount) > MSGlen.lenhypoThresh)
            # noinspection PyTypeChecker
            constantMultiplicator = all(numpy.round(Xarray[0,0], 8) == numpy.round(Xarray[1:,0], 8))
            logging.getLogger(__name__).debug(f"Candidate mostlyAcceptable {mostlyAcceptable} "
                                              f"and has constantMultiplicator {constantMultiplicator}.")
            return mostlyAcceptable and constantMultiplicator


class CategoricalCorrelatedField(fieldtypes.CategoricalCorrelatedField,ABC):
    """
    Abstract class for inferring field types using categorical correlation of n-gram values with external values, e. g.,
    environmental information like addresses from encapsulation.

    Enhancement of fieldtypes.CategoricalCorrelatedField to iteratively check n-grams from size four to one.
    """
    # correlationThresh = 0.8  # Reduced from 0.9 (FH, Sec. 3.2.3)

    @classmethod
    def correlate(cls, messages: List[L2NetworkMessage], n: int = 4):
        """
        Generate n-grams with n's from large to small
        at the same offsets for each message an correlate each n-gram using categorical correlation.

        see fieldtypes.CategoricalCorrelatedField#correlate()
        see HostID for the rationale of this enhancement over FH.

        :param messages: Messages to generate n-grams to correlate to.
        :param n: maximum of n to correlate from large to small
        :return: Correlation values for each offset of n-grams generated from the messages.
        """
        categoricalCorrelation = None
        for n in range(4,0,-1):
            # this is one correlation value for each n-gram starting at the offset
            corrAtOffset = super().correlate(messages, n)
            if categoricalCorrelation is None:  # initial fill
                categoricalCorrelation = [-1] * (len(corrAtOffset) + n - 1)
            if len(corrAtOffset) + n - 1 != len(categoricalCorrelation):  # validity check
                # this should not occur of #correlate() is correct and called with the same set of messages
                raise RuntimeError("Too few values to correlate.")
            for offset, corr in enumerate(corrAtOffset):  # iterate all n-gram offsets
                for nOff in range(offset, offset+n):  # check/set the correlation for ALL bytes of this n-gram
                    if categoricalCorrelation[nOff] < corr:
                        categoricalCorrelation[nOff] = corr
            corRepr = [f"{cc:.3f}" for cc in categoricalCorrelation]
            logging.getLogger(__name__).debug(f"Correlation of {n}-ngrams: {corRepr}")
        return categoricalCorrelation

    @classmethod
    def _combineNgrams2Values(cls, ngrams: Iterable[bytes], values: List[int]):
        """
        The correlation is perfect if null values are omitted

        >>> ngrand = [b'\xa2\xe7',
        ...           b'r\x06',
        ...           b'\x0f?',
        ...           b'd\x8a',
        ...           b'\xa0X',
        ...           b'\x04\xba',
        ...           b'\x19r',
        ...           b'\x17M',
        ...           b',\xda',
        ...           b'9K',
        ...           b'<3',
        ...           b'\xaa\xdf']
        >>> valRnd = ['0.601',
        ...           '0.601',
        ...           '0.601',
        ...           '0.601',
        ...           '0.804',
        ...           '0.804',
        ...           '0.804',
        ...           '0.804',
        ...           '0.804',
        ...           '0.792',
        ...           '0.731',
        ...           '0.722']
        >>> from fieldhunter.inference.fieldtypesRelaxed import CategoricalCorrelatedField
        >>> CategoricalCorrelatedField._combineNgrams2Values(ngrand, valRnd)

        """
        nonNull = list(zip(*filter(lambda x: set(x[0]) != {0}, zip(ngrams, values))))
        if len(nonNull) == 0:
            nonNull = [[],[]]
        return super(CategoricalCorrelatedField, cls)._combineNgrams2Values(*nonNull)


class HostID(CategoricalCorrelatedField, fieldtypes.HostID):
    """
    Relaxed version of host identifier (Host-ID) inference (FH, Sec. 3.2.3)
    Find n-gram that is strongly correlated with IP address of sender.

    see fieldtypes.HostID

    # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # #
    # # We investigated the low categoricalCorrelation for all but one byte within an address field (see NTP and DHCP).
    # # According to NTP offset 12 (REF ID, often DST IP address) and DHCP offsets (12, 17, and) 20 (IPs)
    # # this works in principle, but if the n-gram is too short the correlation gets lost for some n-grams.
    print(tabulate(zip(*[hostidfields.categoricalCorrelation]), showindex="always"))
    from matplotlib import pyplot
    pyplot.bar(range(len(hostidfields.categoricalCorrelation)), hostidfields.categoricalCorrelation)
    pyplot.show()
    # sum([msg.data[20:24] == bytes(map(int, msg.source.rpartition(':')[0].split('.'))) for msg in messages])
    # sum([int.from_bytes(messages[m].data[20:24], "big") == srcs[m] for m in range(len(messages))])
    # # While the whole dhcp.ip.server [20:24] correlates nicely to the IP address, single n-grams don't.
    serverIP = [(int.from_bytes(messages[m].data[20:24], "big"), srcs[m]) for m in range(len(messages))]
    serverIP0 = [(messages[m].data[20], srcs[m]) for m in range(len(messages))]
    serverIP1 = [(messages[m].data[21], srcs[m]) for m in range(len(messages))]
    serverIP2 = [(messages[m].data[22], srcs[m]) for m in range(len(messages))]
    serverIP3 = [(messages[m].data[23], srcs[m]) for m in range(len(messages))]
    # nsp = numpy.array([sip for sip in serverIP])
    # # The correlation is perfect, if null values are omitted
    nsp = numpy.array([sip for sip in serverIP if sip[0] != 0])   #  and sip[0] == sip[1]
    # nsp0 = numpy.array(serverIP0)
    # nsp1 = numpy.array(serverIP1)
    # nsp2 = numpy.array(serverIP2)
    # nsp3 = numpy.array(serverIP3)
    nsp0 = numpy.array([sip for sip in serverIP0 if sip[0] != 0])
    nsp1 = numpy.array([sip for sip in serverIP1 if sip[0] != 0])
    nsp2 = numpy.array([sip for sip in serverIP2 if sip[0] != 0])
    nsp3 = numpy.array([sip for sip in serverIP3 if sip[0] != 0])
    for serverSrcPairs in [nsp, nsp0, nsp1, nsp2, nsp3]:
        print(drv.information_mutual(serverSrcPairs[:, 0], serverSrcPairs[:, 1]) / drv.entropy_joint(serverSrcPairs.T))
    # # Thus, this is no implementation error, but raises doubts about the Host-ID description completeness:
    # # Probably it does not mention an Entropy filter, direction separation, or - most probably -
    # # an iterative n-gram size increase (like for MSGlen). Thus, we implement such an iterative n-gram analysis
    # # in this class's relaxed super-class CategoricalCorrelatedField.
    # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # #
    """


class SessionID(CategoricalCorrelatedField, fieldtypes.SessionID):
    """
    Relaxed version of session identifier (Session-ID) inference (FH, Section 3.2.4)
    Find n-gram that is strongly correlated with IP addresses of sender and receiver
    using categorical correlation like Host-ID.

    see fieldtypes.SessionID

    A problem similar to Host-ID's leads to the same bad quality, thus, we apply the same change via the relaxed
    super-class CategoricalCorrelatedField.
    """
    # correlationThresh = 0.5  # Reduced from 0.9 (FH, Sec. 3.2.3)


class TransID(fieldtypes.TransID):
    """
    Relaxed version of transaction identifier (Trans-ID) inference (FH, Section 3.2.5, Fig. 3 right)

    see fieldtypes.TransID
    """
    transSupportThresh = 0.8  # enough support in conversations (FH, Sec. 3.2.5)
    minFieldLength = 2  # merged n-grams must at least be this amount of bytes long
    # n-gram size is not explicitly given in FH, but the description (merging, sharp drops in entropy in Fig. 6)
    #   leads to assuming it should be 1.
    n = 1
    entropyThresh = 0.8  # Value not given in FH!
    # entropy in c2s/s2c + flows: threshold for high entropy is not given in FH! Use value determined
    #   by own empirics in base.entropyThresh

    def _verticalAndHorizontalRandomNgrams(self):
        """
        Determine n-grams that are "random across vertical and horizontal collections" (FH, Sec. 3.2.5).

        Output is written to self._c2sCombinedOffsets and self._s2cCombinedOffsets.
        Moreover, intermediate results are persisted in instance attributes for evaluation.
        """
        # vertical collections
        c2s, s2c = self._flows.splitDirections()  # type: List[L4NetworkMessage], List[L4NetworkMessage]
        self._c2sEntropyFiltered = type(self).entropyFilteredOffsets(c2s)
        self._s2cEntropyFiltered = type(self).entropyFilteredOffsets(s2c)
        # print('_c2sEntropyFiltered')
        # pprint(self._c2sEntropyFiltered)
        # print('_s2cEntropyFiltered')
        # pprint(self._s2cEntropyFiltered)

        # # horizontal collections: intermediate entropy of n-grams for debugging
        # self._c2sConvsEntropy = dict()
        # for key, conv in self._flows.c2sInConversations().items():
        #     self._c2sConvsEntropy[key] = pyitNgramEntropy(conv, type(self).n)
        # self._s2cConvsEntropy = dict()
        # for key, conv in self._flows.s2cInConversations().items():
        #     self._s2cConvsEntropy[key] = pyitNgramEntropy(conv, type(self).n)
        # print('_c2sConvsEntropy')
        # pprint(self._c2sConvsEntropy)
        # print('_s2cConvsEntropy')
        # pprint(self._s2cConvsEntropy)

        # horizontal collections: entropy of n-gram per the same offset in all messages of one flow direction
        for key, conv in self._flows.c2sInConversations().items():
            # The entropy is too low if the number of specimens is low -> relative to max
            # and ignore conversations of length 1
            # (TODO FH does not specify, but probably require even longer conversations to observe
            #   that the ID changes for each request/reply pair?
            #   "Transaction ID" in DHCP is a FP, since it is actually a Session-ID)
            if len(conv) <= 1:
                continue
            self._c2sConvsEntropyFiltered[key] = type(self).entropyFilteredOffsets(conv, False)
        for key, conv in self._flows.s2cInConversations().items():
            # The entropy is too low if the number of specimens is low -> relative to max
            # and ignore conversations of length 1
            # (TODO FH does not specify, but probably require even longer conversations to observe
            #   that the ID changes for each request/reply pair?
            #   "Transaction ID" in DHCP is a FP, since it is actually a Session-ID)
            if len(conv) <= 1:
                continue
            self._s2cConvsEntropyFiltered[key] = type(self).entropyFilteredOffsets(conv, False)
        # print('_c2sConvsEntropyFiltered')
        # pprint(_c2sConvsEntropyFiltered)
        # print('_s2cConvsEntropyFiltered')
        # pprint(_s2cConvsEntropyFiltered)

        # intersection of all c2s and s2c filtered offset lists (per flow)
        c2sOffsetLists = [set(offsetlist) for offsetlist in self._c2sConvsEntropyFiltered.values()]
        self._c2sHorizontalOffsets = set.intersection(*c2sOffsetLists) if len(c2sOffsetLists) > 0 else set()
        s2cOffsetLists = [set(offsetlist) for offsetlist in self._s2cConvsEntropyFiltered.values()]
        self._s2cHorizontalOffsets = set.intersection(*s2cOffsetLists) if len(s2cOffsetLists) > 0 else set()
        # offsets in _c2sEntropyFiltered where the offset is also in all of the lists of _c2sConvsEntropyFiltered
        # (TODO alternatively, deviating from FH, use the offset for each query specifically?)
        self._c2sCombinedOffsets = self._c2sHorizontalOffsets.intersection(self._c2sEntropyFiltered)
        # offsets in _c2sEntropyFiltered where the offset is also in all of the lists of _s2cConvsEntropyFiltered
        # (TODO alternatively, deviating from FH, use the entry for each response specifically?)
        self._s2cCombinedOffsets = self._s2cHorizontalOffsets.intersection(self._s2cEntropyFiltered)



# Host-ID will always return a subset of Session-ID fields, so Host-ID should get precedence
# MSG-Len would be overwritten by MSG-Type (see SMB: nbss.length), so first use MSG-Len
precedence = {MSGlen.typelabel: 0, MSGtype.typelabel: 1, HostID.typelabel: 2,
              SessionID.typelabel: 3, TransID.typelabel: 4, Accumulator.typelabel: 5}
"""
The order in which to map field types to messages. 
Lower numbers take precedence over higher numbers, so that the type with the higher number will be ignored 
if overlapping at the same offet range in the message.
"""