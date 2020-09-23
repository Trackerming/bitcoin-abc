// Copyright (c) 2019 The Bitcoin Core developers
// Distributed under the MIT software license, see the accompanying
// file COPYING or http://www.opensource.org/licenses/mit-license.php.

#include <chainparams.h>
#include <compressor.h>
#include <core_io.h>
#include <core_memusage.h>
#include <policy/policy.h>
#include <pubkey.h>
#include <script/descriptor.h>
#include <script/script.h>
#include <script/sign.h>
#include <script/signingprovider.h>
#include <script/standard.h>
#include <streams.h>
#include <test/fuzz/fuzz.h>

#include <memory>

void initialize() {
    // Fuzzers using pubkey must hold an ECCVerifyHandle.
    static const auto verify_handle = std::make_unique<ECCVerifyHandle>();
}

void test_one_input(const std::vector<uint8_t> &buffer) {
    const CScript script(buffer.begin(), buffer.end());

    std::vector<uint8_t> compressed;
    (void)CompressScript(script, compressed);

    CTxDestination address;
    (void)ExtractDestination(script, address);

    txnouttype type_ret;
    std::vector<CTxDestination> addresses;
    int required_ret;
    (void)ExtractDestinations(script, type_ret, addresses, required_ret);

    const FlatSigningProvider signing_provider;
    (void)InferDescriptor(script, signing_provider);

    (void)script.IsWitnessProgram();

    (void)IsSolvable(signing_provider, script);

    txnouttype which_type;
    (void)IsStandard(script, which_type);

    (void)RecursiveDynamicUsage(script);

    std::vector<std::vector<uint8_t>> solutions;
    (void)Solver(script, solutions);

    (void)script.HasValidOps();
    (void)script.IsPayToScriptHash();
    (void)script.IsPushOnly();
    (void)script.IsUnspendable();
}
