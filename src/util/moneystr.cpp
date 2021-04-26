// Copyright (c) 2009-2010 Satoshi Nakamoto
// Copyright (c) 2009-2015 The Bitcoin Core developers
// Distributed under the MIT software license, see the accompanying
// file COPYING or http://www.opensource.org/licenses/mit-license.php.

#include <util/moneystr.h>

#include <tinyformat.h>
#include <util/strencodings.h>
#include <util/string.h>

std::string FormatMoney(const Amount amt) {
    // Note: not using straight sprintf here because we do NOT want localized
    // number formatting.
    Amount amt_abs = amt > Amount::zero() ? amt : -amt;
    std::string str =
        strprintf("%d.%08d", amt_abs / COIN, (amt_abs % COIN) / SATOSHI);

    // Right-trim excess zeros before the decimal point:
    int nTrim = 0;
    for (int i = str.size() - 1; (str[i] == '0' && IsDigit(str[i - 2])); --i) {
        ++nTrim;
    }
    if (nTrim) {
        str.erase(str.size() - nTrim, nTrim);
    }

    if (amt < Amount::zero()) {
        str.insert((unsigned int)0, 1, '-');
    }
    return str;
}

bool ParseMoney(const std::string &money_string, Amount &nRet) {
    if (!ValidAsCString(money_string)) {
        return false;
    }
    const std::string str = TrimString(money_string);
    if (str.empty()) {
        return false;
    }

    std::string strWhole;
    Amount nUnits = Amount::zero();
    const char *p = str.c_str();
    for (; *p; p++) {
        if (*p == '.') {
            p++;
            Amount nMult = COIN / 10;
            while (IsDigit(*p) && (nMult > Amount::zero())) {
                nUnits += (*p++ - '0') * nMult;
                nMult /= 10;
            }
            break;
        }
        if (IsSpace(*p)) {
            return false;
        }
        if (!IsDigit(*p)) {
            return false;
        }
        strWhole.insert(strWhole.end(), *p);
    }
    if (*p) {
        return false;
    }
    // guard against 63 bit overflow
    if (strWhole.size() > 10) {
        return false;
    }
    if (nUnits < Amount::zero() || nUnits > COIN) {
        return false;
    }

    Amount nWhole = atoi64(strWhole) * COIN;

    nRet = nWhole + Amount(nUnits);
    return true;
}
