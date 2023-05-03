# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

## [5.0.4] - 2023-05-03

### Fixed 
- Update gas price for shared wallet account creation [#74](https://github.com/CirclesUBI/safe-relay-service/pull/74)

## [5.0.3] - 2023-02-08

### Fixed 
- Update gas price for account sign up [#71](https://github.com/CirclesUBI/safe-relay-service/pull/71)

- Update safe-eth-py package [8e789c](https://github.com/CirclesUBI/safe-relay-service/commit/8e789c17065cb38246f64008a824b04266eeb2ef)
 
## [5.0.2] - 2022-11-28

Fix typo in `config/settings/base.py`.

**Full Changelog**: https://github.com/CirclesUBI/safe-relay-service/compare/5.0.1...v5.0.2

## [5.0.1] - 2022-11-28

### Fixed

- Use the GnosisSafeL2 address by default and add the GnosisSafe address the Safe valid contracts addresses list [#65](https://github.com/CirclesUBI/safe-relay-service/pull/65)

## [5.0.0] - 2022-11-24

### Changed

- Update codebase to `v4.1.0` of [5afe/safe-relay-service](https://github.com/5afe/safe-relay-service) [#61](https://github.com/CirclesUBI/safe-relay-service/pull/61)

### Added

- Compatibility with both versions of the Safe contract (`v1.1.1+Circles`, and `v1.3.0`) [#64](https://github.com/CirclesUBI/safe-relay-service/pull/64)

### Removed

- Remove ETHEREUM_NODE_URL from about view [#61](https://github.com/CirclesUBI/safe-relay-service/pull/61)

## [4.1.13] - 2022-04-25

### Changed

- Increase gas in funding txs [#54](https://github.com/CirclesUBI/safe-relay-service/pull/54)

## [4.1.12] - 2022-04-11

### Changed

- Increase onboarding funding [#53](https://github.com/CirclesUBI/safe-relay-service/pull/53)

## [4.1.11] - 2021-09-09

### Changed

- Migrate ubuntu-16.04 workflows to ubuntu-18.04 [#51](https://github.com/CirclesUBI/safe-relay-service/pull/51)

## [4.1.10] - 2021-09-09

### Changed

- Avoid predicting a new address if there's already one registered [#50](https://github.com/CirclesUBI/safe-relay-service/pull/50)

### Added

- Create RELEASE.md

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
