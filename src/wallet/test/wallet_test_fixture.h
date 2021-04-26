// Copyright (c) 2016 The Bitcoin Core developers
// Distributed under the MIT software license, see the accompanying
// file COPYING or http://www.opensource.org/licenses/mit-license.php.

#ifndef BITCOIN_WALLET_TEST_WALLET_TEST_FIXTURE_H
#define BITCOIN_WALLET_TEST_WALLET_TEST_FIXTURE_H

#include <interfaces/chain.h>
#include <interfaces/wallet.h>
#include <node/context.h>
#include <util/check.h>
#include <wallet/wallet.h>

#include <test/util/setup_common.h>

#include <memory>

/**
 * Testing setup and teardown for wallet.
 */
struct WalletTestingSetup : public TestingSetup {
    explicit WalletTestingSetup(
        const std::string &chainName = CBaseChainParams::MAIN);

    std::unique_ptr<interfaces::Chain> m_chain;
    std::unique_ptr<interfaces::ChainClient> m_chain_client =
        interfaces::MakeWalletClient(*m_chain, *Assert(m_node.args), {});
    CWallet m_wallet;
    std::unique_ptr<interfaces::Handler> m_chain_notifications_handler;
};

#endif // BITCOIN_WALLET_TEST_WALLET_TEST_FIXTURE_H
