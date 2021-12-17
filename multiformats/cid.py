"""
    Implementation of the [CID spec](https://github.com/multiformats/cid).

    Core functionality is provided by the `CID` class:

    ```py
    >>> from multiformats import CID
    ```

    CIDs can be decoded from bytestrings or (multi)base encoded strings:

    ```py
    >>> cid = CID.decode("zb2rhe5P4gXftAwvA4eXQ5HJwsER2owDyS9sKaQRRVQPn93bA")
    >>> cid
    CID('base58btc', 1, 'raw',
        '12206e6ff7950a36187a801613426e858dce686cd7d7e3c0fc42ee0330072d245c95')
    ```

    CIDs can be created programmatically, and their fields accessed individually:

    ```py
    >>> cid = CID("base58btc", 1, "raw",
    ... "12206e6ff7950a36187a801613426e858dce686cd7d7e3c0fc42ee0330072d245c95")
    >>> cid.base
    Multibase(name='base58btc', code='z',
              status='default', description='base58 bitcoin')
    >>> cid.codec
    Multicodec(name='raw', tag='ipld', code='0x55',
               status='permanent', description='raw binary')
    >>> cid.hashfun
    Multicodec(name='sha2-256', tag='multihash', code='0x12',
               status='permanent', description='')
    >>> cid.digest.hex()
    '12206e6ff7950a36187a801613426e858dce686cd7d7e3c0fc42ee0330072d245c95'
    >>> cid.raw_digest.hex()
    '6e6ff7950a36187a801613426e858dce686cd7d7e3c0fc42ee0330072d245c95'
    ```

    CIDs can be converted to bytestrings or (multi)base encoded strings:

    ```py
    >>> str(cid)
    'zb2rhe5P4gXftAwvA4eXQ5HJwsER2owDyS9sKaQRRVQPn93bA'
    >>> bytes(cid).hex()
    '015512206e6ff7950a36187a801613426e858dce686cd7d7e3c0fc42ee0330072d245c95'
    >>> cid.encode("base32") # encode with different multibase
    'bafkreidon73zkcrwdb5iafqtijxildoonbwnpv7dyd6ef3qdgads2jc4su'
    ```

    Additionally, the `CID.peer_id` static method can be used to pack the raw
    hash of a public key into a CIDv1 [PeerID](https://docs.libp2p.io/concepts/peer-id/),
    according to the [PeerID spec](https://github.com/libp2p/specs/blob/master/peer-ids/peer-ids.md).

    For full details, see the `CID` documentation below.

"""

from typing import Any, cast, FrozenSet, Tuple, Type, TypeVar, Union
from typing_extensions import Literal, Final
from typing_validation import validate

from bases import base58btc
from multiformats import varint, multicodec, multibase, multihash

from multiformats.multicodec import Multicodec
from multiformats.multibase import Multibase
from multiformats.multihash import Multihash, _validate_raw_digest_size
from multiformats.varint import BytesLike, byteslike

_CIDSubclass = TypeVar("_CIDSubclass", bound="CID")

CIDVersion = Literal[0, 1]
CIDVersionNumbers: Final[FrozenSet[int]] = frozenset({0, 1})

def _binary_cid_from_str(cid: str) -> Tuple[bytes, Multibase]:
    if len(cid) == 46 and cid.startswith("Qm"):
        # CIDv0 to be decoded as base58btc
        return base58btc.decode(cid), multibase.get("base58btc")
    mb, b = multibase.decode_raw(cid)
    if b[0] ==  0x12:
        # CIDv0 may not be multibase encoded (0x12 is the first byte of sha2-256 multihashes)
        # CIDv18 (first byte 18=0x12) will be skipped to prevent ambiguity
        raise ValueError("CIDv0 may not be multibase encoded (found multibase encoded bytes starting with 0x12).")
    return b, mb

def _CID_validate_multibase(base: Union[str, Multibase]) -> Multibase:
    if isinstance(base, str):
        base = multibase.get(base)
    else:
        multibase.validate_multibase(base)
    return base

def _CID_validate_multicodec(codec: Union[str, int, Multicodec]) -> Multicodec:
    if isinstance(codec, str):
        codec = multicodec.get(codec)
    elif isinstance(codec, int):
        codec = multicodec.get(code=codec)
    else:
        multicodec.validate_multicodec(codec)
    return codec

def _CID_validate_multihash(hashfun: Union[str, int, Multihash]) -> Multihash:
    if isinstance(hashfun, str):
        hashfun = multihash.get(hashfun)
    elif isinstance(hashfun, int):
        hashfun = multihash.get(code=hashfun)
    else:
        pass
    return hashfun

def _CID_validate_raw_digest(raw_digest: Union[str, BytesLike], hashfun: Multihash) -> bytes:
    if isinstance(raw_digest, str):
        raw_digest = bytes.fromhex(raw_digest)
    else:
        validate(raw_digest, BytesLike)
        if not isinstance(raw_digest, bytes):
            raw_digest = bytes(raw_digest)
    _, max_digest_size = hashfun.implementation
    _validate_raw_digest_size(hashfun.name, raw_digest, max_digest_size)
    return raw_digest

def _CID_validate_multihash_digest(digest: Union[str, BytesLike]) -> Tuple[Multihash, bytes]:
    if isinstance(digest, str):
        digest = bytes.fromhex(digest)
    raw_digest: BytesLike
    code, raw_digest = multihash.decode_raw(digest)
    hashfun = _CID_validate_multihash(code)
    raw_digest = _CID_validate_raw_digest(raw_digest, hashfun)
    return hashfun, raw_digest

def _CID_validate_version(version: int, base: Multibase, codec: Multicodec, hashfun: Multihash) -> int:
    if version in (2, 3):
        raise ValueError("CID versions 2 and 3 are reserved for future use.")
    if version not in (0, 1):
        raise ValueError(f"CID version {version} is not allowed.")
    if version == 0:
        if base.name != 'base58btc':
            raise ValueError(f"CIDv0 multibase must be 'base58btc', found {repr(base.name)} instead.")
        if codec.name != "dag-pb":
            raise ValueError(f"CIDv0 multicodec must be 'dag-pb', found {repr(codec.name)} instead.")
        if hashfun.name != "sha2-256":
            raise ValueError(f"CIDv0 multihash must be 'sha2-256', found {repr(hashfun.name)} instead.")
    return version


class CID:
    """

    Container class for [Content IDentifiers](https://github.com/multiformats/cid).
    CIDs can be decoded from a bytestring or a (multi)base encoded string, using `CID.decode`:

    ```py
    >>> cid = CID.decode("zb2rhe5P4gXftAwvA4eXQ5HJwsER2owDyS9sKaQRRVQPn93bA")
    >>> cid
    CID('base58btc', 1, 'raw',
        '12206e6ff7950a36187a801613426e858dce686cd7d7e3c0fc42ee0330072d245c95')
    ```

    CIDs can be explicitly instantiated by passing the `base`, `version`, `codec` and multihash `digest` to the constructor:

    ```py
    >>> cid = CID("base58btc", 1, "raw",
    ... "12206e6ff7950a36187a801613426e858dce686cd7d7e3c0fc42ee0330072d245c95")
    >>> str(cid)
    'zb2rhe5P4gXftAwvA4eXQ5HJwsER2owDyS9sKaQRRVQPn93bA'
    ```

    Alternatively, a `(multihash_codec, raw_digest)` pair can be passed in lieu of `digest`:

    ```py
    >>> raw_digest = bytes.fromhex(
    ... "6e6ff7950a36187a801613426e858dce686cd7d7e3c0fc42ee0330072d245c95")
    >>> cid = CID("base58btc", 1, "raw", ("sha2-256", raw_digest))
    >>> str(cid)
    'zb2rhe5P4gXftAwvA4eXQ5HJwsER2owDyS9sKaQRRVQPn93bA'
    ```

    The `digest` and `raw_digest` parameters can be passed either as `bytes`-like objects
    or as the corresponding hex strings (which will be converted to `bytes` using `bytes.fromhex`):

    ```py
    >>> isinstance(raw_digest, bytes)
    True
    >>> raw_digest.hex()
    '6e6ff7950a36187a801613426e858dce686cd7d7e3c0fc42ee0330072d245c95'
    ```

    Note: the hex strings are not multibase encoded.

    Calling `bytes(cid)` returns the binary representation of `cid`, as a `bytes` object:

    ```py
    >>> cid = CID("base58btc", 1, "raw",
    ... "12206e6ff7950a36187a801613426e858dce686cd7d7e3c0fc42ee0330072d245c95")
    >>> raw_digest.hex()
            '6e6ff7950a36187a801613426e858dce686cd7d7e3c0fc42ee0330072d245c95'
    >>> bytes(cid).hex()
    '015512206e6ff7950a36187a801613426e858dce686cd7d7e3c0fc42ee0330072d245c95'
    #^^   0x01 = CIDv1
    #  ^^ 0x55 = 'raw' codec
    >>> bytes(cid)
    ```

    """

    _base: Multibase
    _version: CIDVersion
    _codec: Multicodec
    _hashfun: Multihash
    _digest: bytes

    __slots__ = ("__weakref__", "_base", "_version", "_codec", "_hashfun", "_digest")

    def __new__(cls: Type[_CIDSubclass],
                base: Union[str, Multibase],
                version: int,
                codec: Union[str, int, Multicodec],
                digest: Union[str, BytesLike, Tuple[Union[str, int, Multihash], Union[str, BytesLike]]],
                ) -> _CIDSubclass:
        # pylint: disable = too-many-arguments
        base = _CID_validate_multibase(base)
        codec = _CID_validate_multicodec(codec)
        raw_digest: Union[str, bytes]
        hashfun: Union[str, int, Multihash]
        if isinstance(digest, (str,)+byteslike):
            hashfun, raw_digest = _CID_validate_multihash_digest(digest)
        else:
            validate(digest, Tuple[Union[str, int, Multihash], Union[str, BytesLike]])
            hashfun, raw_digest = digest
            hashfun = _CID_validate_multihash(hashfun)
            raw_digest = _CID_validate_raw_digest(raw_digest, hashfun)
        version = _CID_validate_version(version, base, codec, hashfun)
        if isinstance(digest, bytes):
            return CID._new_instance(cls, base, version, codec, hashfun, digest)
        return CID._new_instance(cls, base, version, codec, hashfun, (hashfun, raw_digest))

    @staticmethod
    def _new_instance(CID_subclass: Type[_CIDSubclass],
                      base: Multibase,
                      version: int,
                      codec: Multicodec,
                      hashfun: Multihash,
                      digest: Union[bytes, Tuple[Multihash, bytes]],
                     ) -> _CIDSubclass:
        # pylint: disable = too-many-arguments
        instance: _CIDSubclass = super().__new__(CID_subclass)
        instance._base = base
        assert version in (0, 1)
        instance._version = cast(Literal[0, 1], version)
        instance._codec = codec
        instance._hashfun = hashfun
        if isinstance(digest, bytes):
            instance._digest = digest
        elif isinstance(digest, byteslike):
            instance._digest = bytes(digest)
        else:
            _hashfun, raw_digest = digest
            if not isinstance(raw_digest, bytes):
                raw_digest = bytes(raw_digest)
            assert _hashfun == hashfun, "You passed different multihashes to a _new_instance call with digest as a pair."
            instance._digest = hashfun.encode(raw_digest)
        return instance

    @property
    def version(self) -> CIDVersion:
        """
            CID version.

            Example usage:

            ```py
            >>> s = "zb2rhe5P4gXftAwvA4eXQ5HJwsER2owDyS9sKaQRRVQPn93bA"
            >>> cid = CID.decode(s)
            >>> cid.version
            1
            ```
        """
        return self._version

    @property
    def base(self) -> Multibase:
        """
            Multibase used to encode the CID:

            - if a CIDv1 was decoded from a multibase-encoded string, the encoding multibase is used
            - if a CIDv1 was decoded from a bytestring, the 'base58btc' multibase is used
            - for a CIDv0, 'base58btc' is always used

            Example usage:

            ```py
            >>> s = "zb2rhe5P4gXftAwvA4eXQ5HJwsER2owDyS9sKaQRRVQPn93bA"
            >>> cid = CID.decode(s)
            >>> cid.base
            Multibase(name='base58btc', code='z',
                      status='default', description='base58 bitcoin')
            ```
        """
        return self._base

    @property
    def codec(self) -> Multicodec:
        """
            Codec that the multihash digest refers to.

            Example usage:

            ```py
            >>> s = "zb2rhe5P4gXftAwvA4eXQ5HJwsER2owDyS9sKaQRRVQPn93bA"
            >>> cid = CID.decode(s)
            >>> cid.codec
            Multicodec(name='raw', tag='ipld', code='0x55',
                       status='permanent', description='raw binary')
            ```
        """
        return self._codec

    @property
    def hashfun(self) -> Multihash:
        """
            Multihash used to produce the multihash digest.

            Example usage:

            ```py
            >>> s = "zb2rhe5P4gXftAwvA4eXQ5HJwsER2owDyS9sKaQRRVQPn93bA"
            >>> cid = CID.decode(s)
            >>> cid.hashfun
            Multicodec(name='sha2-256', tag='multihash', code='0x12',
                       status='permanent', description='')
            ```
        """
        return self._hashfun

    @property
    def digest(self) -> bytes:
        """
            Multihash digest.

            Example usage:

            ```py
            >>> s = "zb2rhe5P4gXftAwvA4eXQ5HJwsER2owDyS9sKaQRRVQPn93bA"
            >>> cid = CID.decode(s)
            >>> cid.digest.hex()
            '12206e6ff7950a36187a801613426e858dce686cd7d7e3c0fc42ee0330072d245c95'
            ```
        """
        return self._digest

    @property
    def raw_digest(self) -> bytes:
        """
            Raw hash digest, decoded from the multihash digest.

            Example usage:

            ```py
            >>> s = "zb2rhe5P4gXftAwvA4eXQ5HJwsER2owDyS9sKaQRRVQPn93bA"
            >>> cid = CID.decode(s)
            >>> cid.raw_digest.hex()
            '6e6ff7950a36187a801613426e858dce686cd7d7e3c0fc42ee0330072d245c95'
            ```
        """
        return multihash.decode(self._digest)

    @property
    def human_readable(self) -> str:
        """
            Human-readable representation of the CID.

            Example usage:

            ```py
            >>> s = "zb2rhe5P4gXftAwvA4eXQ5HJwsER2owDyS9sKaQRRVQPn93bA"
            >>> cid = CID.decode(s)
            >>> cid.human_readable
            'base58btc - cidv1 - raw - (sha2-256 : 256 : 6E6FF7950A36187A801613426E858DCE686CD7D7E3C0FC42EE0330072D245C95)'
            ```
        """
        raw_digest = self.raw_digest
        hashfun_str = f"({self.hashfun.name} : {len(raw_digest)*8} : {raw_digest.hex().upper()})"
        return f"{self.base.name} - cidv{self.version} - {self.codec.name} - {hashfun_str}"

    def encode(self, base: Union[None, str, Multibase] = None) -> str:
        """
            Encodes the CID using a given multibase. If no multibase is give,
            the CID's own multibase is used by default.

            Example usage:

            ```py
            >>> s = "zb2rhe5P4gXftAwvA4eXQ5HJwsER2owDyS9sKaQRRVQPn93bA"
            >>> cid = CID.decode(s)
            >>> cid.encode() # default: cid.base
            'zb2rhe5P4gXftAwvA4eXQ5HJwsER2owDyS9sKaQRRVQPn93bA'
            >>> cid.encode("base32")
            'bafkreidon73zkcrwdb5iafqtijxildoonbwnpv7dyd6ef3qdgads2jc4su'
            ```
        """
        if self.version == 0:
            if base is not None:
                raise ValueError("CIDv0 cannot be multibase-encoded, please set multibase=None.")
            return base58btc.encode(bytes(self))
        if base is None or base == self.base:
            base = self.base # use CID's own multibase as default
        else:
            if isinstance(base, str):
                base = multibase.get(base)
            else:
                multibase.validate_multibase(base)
        return base.encode(bytes(self))

    def set(self, *,
            base: Union[None, str, Multibase] = None,
            version: Union[None, int] = None,
            codec: Union[None, str, int, Multicodec] = None
           ) -> "CID":
        """
            Returns a new CID obtained by setting new values for one or more of:
            `base`, `version`, or `codec`.

            Example usage:

            ```py
            >>> s = "zb2rhe5P4gXftAwvA4eXQ5HJwsER2owDyS9sKaQRRVQPn93bA"
            >>> cid = CID.decode(s)
            >>> cid
            CID('base58btc', 1, 'raw',
            '12206e6ff7950a36187a801613426e858dce686cd7d7e3c0fc42ee0330072d245c95')
            >>> cid.set(base="base32")
            CID('base32', 1, 'raw',
            '12206e6ff7950a36187a801613426e858dce686cd7d7e3c0fc42ee0330072d245c95')
            >>> cid.set(codec="dag-cbor")
            CID('base58btc', 1, 'dag-cbor',
            '12206e6ff7950a36187a801613426e858dce686cd7d7e3c0fc42ee0330072d245c95')
            >>> cid.set(version=0, codec="dag-pb")
            CID('base58btc', 0, 'dag-pb',
            '12206e6ff7950a36187a801613426e858dce686cd7d7e3c0fc42ee0330072d245c95')
            >>> cid
            CID('base58btc', 1, 'raw',
            '12206e6ff7950a36187a801613426e858dce686cd7d7e3c0fc42ee0330072d245c95')
            # Note: 'CID.set' returns new instances,
            #       the original 'cid' instance is unchanged
            ```

            If setting `version` to 0, `base` must be 'base58btc' and `codec` must be 'dag-pb'.

            ```py
            >>> s = "zb2rhe5P4gXftAwvA4eXQ5HJwsER2owDyS9sKaQRRVQPn93bA"
            >>> cid = CID.decode(s)
            >>> cid
            CID('base58btc', 1, 'raw',
            '12206e6ff7950a36187a801613426e858dce686cd7d7e3c0fc42ee0330072d245c95')
            >>> cid.set(version=0, codec="dag-pb")
            CID('base58btc', 0, 'dag-pb',
            '12206e6ff7950a36187a801613426e858dce686cd7d7e3c0fc42ee0330072d245c95')
            >>> cid.set(version=0)
            ValueError: CIDv0 multicodec must be 'dag-pb', found 'raw' instead.
            >>> cid.set(version=0, codec="dag-pb", base="base32")
            ValueError: CIDv0 multibase must be 'base58btc', found 'base32' instead
            ```

        """
        hashfun = self.hashfun
        digest = self.digest
        if base is not None and base not in (self.base, self.base.name):
            base = _CID_validate_multibase(base)
        else:
            base = self.base
        if codec is not None and codec not in (self.codec, self.codec.name, self.codec.code):
            codec = _CID_validate_multicodec(codec)
        else:
            codec = self.codec
        if version is not None and version != self.version:
            _CID_validate_version(version, base, codec, hashfun)
        else:
            version = self.version
        return CID._new_instance(CID, base, version, codec, hashfun, digest)

    def __bytes__(self) -> bytes:
        if self.version == 0:
            return self.digest
        return varint.encode(self.version)+varint.encode(self.codec.code)+self.digest

    def __str__(self) -> str:
        return self.encode()

    def __repr__(self) -> str:
        mb = self.base.name
        v = self.version
        mc = self.codec.name
        d = self.digest
        return f"CID({repr(mb)}, {v}, {repr(mc)}, {repr(d.hex())})"

    @property
    def _as_tuple(self) -> Tuple[Type["CID"], Multibase, int, Multicodec, bytes]:
        return (CID, self.base, self.version, self.codec, self.digest)

    def __hash__(self) -> int:
        return hash(self._as_tuple)

    def __eq__(self, other: Any) -> bool:
        if self is other:
            return True
        if not isinstance(other, CID):
            return NotImplemented
        return self._as_tuple == other._as_tuple

    @staticmethod
    def decode(cid: Union[str, BytesLike]) -> "CID":
        """
            Decodes a CID from a bytestring or a hex string (which will be converted to `bytes`
            using `bytes.fromhex`). Note: the hex string is not multibase encoded.

            Example usage for CIDv1 multibase-encoded string:

            ```py
            >>> s = "zb2rhe5P4gXftAwvA4eXQ5HJwsER2owDyS9sKaQRRVQPn93bA"
            >>> CID.decode(s)
            CID('base58btc', 1, 'raw',
            '12206e6ff7950a36187a801613426e858dce686cd7d7e3c0fc42ee0330072d245c95')
            ```

            Example usage for CIDv1 bytestring (multibase always set to 'base58btc'):

            ```py
            >>> b = bytes.fromhex(
            ... "015512206e6ff7950a36187a801613426e85"
            ... "8dce686cd7d7e3c0fc42ee0330072d245c95")
            >>> CID.decode(b)
            CID('base58btc', 1, 'raw',
            '12206e6ff7950a36187a801613426e858dce686cd7d7e3c0fc42ee0330072d245c95')
            ```

            Example usage for CIDv0 base58-encoded string:

            ```py
            >>> s = "QmbWqxBEKC3P8tqsKc98xmWNzrzDtRLMiMPL8wBuTGsMnR"
            >>> CID.decode(s)
            CID('base58btc', 0, 'dag-pb',
            '1220c3c4733ec8affd06cf9e9ff50ffc6bcd2ec85a6170004bb709669c31de94391a')
            ```

            Example usage for CIDv0 bytestring (multibase always set to 'base58btc'):

            ```py
            >>> b = bytes.fromhex(
            ... "1220c3c4733ec8affd06cf9e9ff50ffc6b"
            ... "cd2ec85a6170004bb709669c31de94391a")
            >>> CID.decode(b)
            CID('base58btc', 0, 'dag-pb',
            '1220c3c4733ec8affd06cf9e9ff50ffc6bcd2ec85a6170004bb709669c31de94391a')
            ```

        """
        if isinstance(cid, str):
            cid, mb = _binary_cid_from_str(cid)
        else:
            mb = multibase.get("base58btc")
        validate(cid, BytesLike)
        cid = memoryview(cid)
        # if len(cid) == 34 and cid.startswith(b"\x12\x20"):
        if len(cid) == 34 and cid[0] == 0x12 and cid[1] == 0x20:
            v = 0 # CID version
            mc_code = 0x70 # multicodec.get("dag-pb")
            digest = cid  # multihash digest is what's left
        else:
            v, _, cid = varint.decode_raw(cid) # CID version
            if v == 0:
                raise ValueError("CIDv0 is malformed.")
            if v in (2, 3):
                raise ValueError("CID versions 2 and 3 are reserved for future use.")
            if v != 1:
                raise ValueError(f"CIDv{v} is currently not supported.")
            mc_code, _, cid = varint.decode_raw(cid) # multicodec
            digest = cid # multihash digest is what's left
        mc = multicodec.get(code=mc_code)
        mh_code, _ = multihash.decode_raw(digest)
        mh = multihash.get(code=mh_code)
        return CID._new_instance(CID, mb, v, mc, mh, digest)

    @staticmethod
    def peer_id(pk_bytes: Union[str, BytesLike]) -> "CID":
        """
            Wraps the raw hash of a public key into a [PeerID](https://docs.libp2p.io/concepts/peer-id/), as a CIDv1.

            The `pk_bytes` argument should be the binary public key, encoded according to the
            [PeerID spec](https://github.com/libp2p/specs/blob/master/peer-ids/peer-ids.md).
            This can be passed as a bytestring or as a hex string (which will be converted to `bytes` using `bytes.fromhex`).
            Note: the hex string is not multibase encoded.

            Example usage with Ed25519 public key:

            ```py
            >>> pk_bytes = bytes.fromhex(
            ... "1498b5467a63dffa2dc9d9e069caf075d16fc33fdd4c3b01bfadae6433767d93")
            ... # a 32-byte Ed25519 public key
            >>> peer_id = CID.peer_id(pk_bytes)
            >>> peer_id
            CID('base32', 1, 'libp2p-key',
            '00201498b5467a63dffa2dc9d9e069caf075d16fc33fdd4c3b01bfadae6433767d93')
            #^^   0x00 = 'identity' multihash used (public key length <= 42)
            #  ^^ 0x20 = 32-bytes of raw hash digestlength
            >>> str(peer_id)
            'bafzaaiautc2um6td375c3soz4bu4v4dv2fx4gp65jq5qdp5nvzsdg5t5sm'
            ```

            Snippet showing how to obtain the [Ed25519](https://cryptography.io/en/latest/hazmat/primitives/asymmetric/ed25519/)
            public key bytestring using the [`cryptography`](https://github.com/pyca/cryptography) library:

            ```py
            >>> from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
            >>> from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat
            >>> private_key = Ed25519PrivateKey.generate()
            >>> public_key = private_key.public_key()
            >>> pk_bytes = public_key.public_bytes(
            ...     encoding=Encoding.Raw,
            ...     format=PublicFormat.Raw
            ... )
            >>> pk_bytes.hex()
            "1498b5467a63dffa2dc9d9e069caf075d16fc33fdd4c3b01bfadae6433767d93"
            ```

            Example usage with DER-encoded RSA public key:

            ```py
            >>> pk_bytes = bytes.fromhex(
            ... "30820122300d06092a864886f70d01010105000382010f003082010a02820101"
            ... "009a56a5c11e2705d0bfe0cd1fa66d5e519095cc741b62ed99ddf129c32e046e"
            ... "5ba3958bb8a068b05a95a6a0623cc3c889b1581793cd84a34cc2307e0dd74c70"
            ... "b4f230c74e5063ecd8e906d372be4eba13f47d04427a717ac78cb12b4b9c2ab5"
            ... "591f36f98021a70f84d782c36c51819054228ff35a45efa3f82b27849ec89036"
            ... "26b4a4c4b40f9f74b79caf55253687124c79cb10cd3bc73f0c44fbd341e5417d"
            ... "2e85e900d22849d2bc85ca6bf037f1f5b4f9759b4b6942fccdf1140b30ea7557"
            ... "87deb5c373c5953c14d64b523959a76a32a599903974a98cf38d4aaac7e359f8"
            ... "6b00a91dcf424bf794592139e7097d7e65889259227c07155770276b6eda4cec"
            ... "370203010001")
            ... # a 294-byte RSA public key
            >>> peer_id = CID.peer_id(pk_bytes)
            >>> peer_id
            CID('base32', 1, 'libp2p-key',
            '1220c1a6513ffb14f202f75453c49666a5b9d7ed9a1a068891daf824d477573f829f')
            #^^   0x12 = 'sha2-256' multihash used (public key length > 42)
            #  ^^ 0x20 = 32-bytes of raw hash digest length
            >>> str(peer_id)
            'bafzbeigbuzit76yu6ibpovctyslgnjnz27wzugqgrci5v6be2r3vop4ct4'
            ```

            Snippet showing how to obtain the [RSA](https://cryptography.io/en/latest/hazmat/primitives/asymmetric/rsa/)
            public key bytestring using the [`cryptography`](https://github.com/pyca/cryptography) library:

            ```py
            >>> from cryptography.hazmat.primitives.asymmetric import rsa
            >>> from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat
            >>> private_key = rsa.generate_private_key(
            ...     public_exponent=65537,
            ...     key_size=2048,
            ... )
            >>> public_key = private_key.public_key()
            >>> pk_bytes = public_key.public_bytes(
            ...     encoding=Encoding.DER,
            ...     format=PublicFormat.SubjectPublicKeyInfo
            ... )
            >>> pk_bytes.hex()
            "30820122300d06092a864886f70d01010105000382010f003082010a02820101"
            "009a56a5c11e2705d0bfe0cd1fa66d5e519095cc741b62ed99ddf129c32e046e"
            "5ba3958bb8a068b05a95a6a0623cc3c889b1581793cd84a34cc2307e0dd74c70"
            "b4f230c74e5063ecd8e906d372be4eba13f47d04427a717ac78cb12b4b9c2ab5"
            "591f36f98021a70f84d782c36c51819054228ff35a45efa3f82b27849ec89036"
            "26b4a4c4b40f9f74b79caf55253687124c79cb10cd3bc73f0c44fbd341e5417d"
            "2e85e900d22849d2bc85ca6bf037f1f5b4f9759b4b6942fccdf1140b30ea7557"
            "87deb5c373c5953c14d64b523959a76a32a599903974a98cf38d4aaac7e359f8"
            "6b00a91dcf424bf794592139e7097d7e65889259227c07155770276b6eda4cec"
            "370203010001"
            ```
        """
        if isinstance(pk_bytes, str):
            pk_bytes = bytes.fromhex(pk_bytes)
        else:
            validate(pk_bytes, BytesLike)
        if len(pk_bytes) <= 42:
            mh = multihash.get("identity")
            digest = multihash.digest(pk_bytes, mh)
        else:
            mh = multihash.get("sha2-256")
            digest = multihash.digest(pk_bytes, mh)
        mc = multicodec.get(code=0x72) # multicodec.get("libp2p-key")
        mb = multibase.get("base32")
        return CID._new_instance(CID, mb, 1, mc, mh, digest)