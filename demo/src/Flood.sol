// SPDX-License-Identifier: MIT
pragma solidity 0.8.24;

interface IToken {
    function transferFrom(address from, address to, uint256 value) external returns (bool);
}

/// The demo's flood: n transfers of `value` of `token` from the caller to `to` in one transaction
/// (n Transfer logs out of the caller). The caller approves this contract first.
contract Flood {
    function run(address token, address to, uint256 value, uint256 n) external {
        for (uint256 i = 0; i < n; i++) {
            require(IToken(token).transferFrom(msg.sender, to, value), "transferFrom");
        }
    }
}
