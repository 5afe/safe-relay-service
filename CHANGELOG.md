# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

## [4.1.9] - 2021-05-25

### Fixed

- Fix organization funding gas limit [#46](https://github.com/CirclesUBI/safe-relay-service/pull/46)

## [4.1.8] - 2021-05-05

### Changed

- Added more logging for safe address prediction v4.1.8 [61870cc](https://github.com/CirclesUBI/safe-relay-service/commit/61870cc1659c970a1b083dd6bde44744d5187aca)

## [4.1.7] - 2021-03-11

### Changed

- Rebased to latest Gnosis Relayer version (`3.12.2`) including Web3 hot fix [a6e57aa](https://github.com/gnosis/safe-relay-service/commit/a6e57aa07c38dd782155509906f1d9e42b1486a1)

## [4.1.6] - 2021-03-01

### Fixed

- Temporarily use patched `gnosis-py` version to work around `Web3.py` issue [#1888](https://github.com/ethereum/web3.py/issues/1888) [e0c0561](https://github.com/CirclesUBI/safe-relay-service/commit/e0c056190e41baa4634afaf303563d1d55e69bb3)

## [4.1.5] - 2021-02-19

### Changed

- Rebased to latest Gnosis Relayer version (`3.12.1`) including Django JSON Field API updates [0a7c759](https://github.com/gnosis/safe-relay-service/commit/0a7c759ddb0475362eb81c4ec4055a602599eaab)

## [4.1.4] - 2021-02-19

- See `4.1.5`

## [4.1.3] - 2021-02-15

### Changed

- Wait longer for block confirmations to mark txs as mined [#36](https://github.com/CirclesUBI/safe-relay-service/pull/36)
