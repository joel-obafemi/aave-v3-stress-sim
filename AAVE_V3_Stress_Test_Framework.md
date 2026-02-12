# Aave V3 (Ethereum) Stress-Test Framework: ETH Market Under Pressure

## 1. Scope Definition

**Target Protocol:** Aave V3 on Ethereum Mainnet.
**Asset Focus:** ETH (Ethereum).
**Role of ETH:**
*   **Collateral:** Users supplying ETH (or Liquid Staking Tokens like stETH/wstETH if treated as ETH-equivalent for this specific stress scope, though strictly "ETH" usually implies native/WETH) to borrow stablecoins (USDC, USDT, DAI) or other assets (WBTC).
*   **Borrowed Asset:** Users borrowing ETH against stablecoin or WBTC collateral (Short ETH positions).

**Positions in Scope:**
*   **All Active Positions:** Analysis covers the entire set of user addresses interacting with the ETH reserve.
*   **Segmentation:**
    *   *Standard Users:* Simple Supply/Borrow.
    *   *Loopers:* Recursive leverage (Supply ETH -> Borrow Stable -> Swap to ETH -> Supply ETH). *Note: This is critical for unwinding logic.*
    *   *Whales:* Top 1% of addresses by TVL, as they pose systemic liquidation risk due to slippage.

**Rationale:**
This scope captures the primary insolvency risks. ETH is the largest collateral asset; a crash affects the system's solvency most acutely. Excluding cross-chain portals (Portals V3) and Isolation Mode assets simplifies the model to focus on the core solvency engine of the High Efficiency Mode (E-Mode) or standard configuration where most capital resides.

---

## 2. Explicit Assumptions

### Base Case vs. Stress Case

| Parameter | Base Case (Normal Operations) | Stress Case (Scenario A: 30% Shock) |
| :--- | :--- | :--- |
| **ETH Price Decline** | 0% (Stable) | **-30%** |
| **Time Horizon** | N/A | **6 Hours** (Flash Crash) |
| **Market Liquidity** | 100% of Avg Daily Volume (ADV) | **20% of ADV** (Liquidity dries up) |
| **Gas Prices** | ~20 gwei | **200+ gwei** (Network Congestion) |
| **User Behavior** | Rational/Responsive | **Passive** (No repayments/collateral top-ups) |
| **Liquidator Behavior**| Profitable if ROI > Gas | **Risk-Averse** (Require higher premium; limited capital) |
| **Oracle Latency** | Standard Chainlink updates | **Standard** (Assume Oracles function correctly) |

### Key Assumptions Justification
1.  **Passive Users:** In a 6h crash, retail users often cannot react in time due to sleep cycles or UI congestion. Assuming 0% repayment is conservative but appropriate for stress testing.
2.  **Liquidator Capital:** We assume liquidators have capital but are bound by on-chain liquidity (DEX depth) to exit the seized collateral.
3.  **Oracle Pacing:** Aave V3 uses Chainlink. We assume price updates trigger correctly when deviation thresholds (usually 0.5% or 1% for ETH) are met.

---

## 3. Required Data Inputs

To run this simulation, the following datasets are required (snapshot at block height $H$):

**Protocol Data (Source: Aave Protocol Subgraph / On-chain query):**
1.  **User Reserve Data:**
    *   `userAddress`
    *   `scaledATokenBalance` (Supply)
    *   `scaledVariableDebtTokenBalance` (Borrow)
    *   `usageAsCollateralEnabled` (Bool)
2.  **Reserve Configuration:**
    *   `LiquidationThreshold` (LT) - e.g., 82.5% for ETH.
    *   `LoanToValue` (LTV) - e.g., 80%.
    *   `LiquidationBonus` (LB) - e.g., 5%.
    *   `ReserveFactor`
    *   `Decimals`
    *   `OracleAddress`

**Market Data (Source: Coingecko / CEX/DEX Data):**
1.  **ETH/USD Historical Depth:** Order book depth +/- 2% and +/- 30% to model slippage.
2.  **Gas Price History:** To calculate minimum profitable liquidation size.

---

## 4. Modeling Logic & Formulas

### A. Health Factor (HF) Recalculation
The core metric determining liquidation eligibility.

$$
HF_{user} = \frac{\sum (Collateral_i \times Price_i \times LT_i)}{\sum (Borrow_j \times Price_j_{ETH})}
$$

*   **Shock Logic:** If ETH price drops by $P_{drop}\%$ (30%), update $Price_{ETH\_new} = Price_{ETH\_old} \times (1 - 0.30)$.
*   **Recalculation:** Re-evaluate $HF$ for all users. If $HF < 1.0$, user is **Liquidatable**.

### B. Liquidation Mechanics
If $HF < 1.0$, a liquidator can repay up to 50% of the debt (Close Factor) to seize collateral.

**Max Liquidatable Amount:**
$$
Debt_{repaid} = \min(Debt_{total} \times 0.5, \text{Amount needed to restore HF > 1})
$$

**Collateral Seized:**
$$
Collateral_{seized} = \frac{Debt_{repaid} \times (1 + LB)}{Price_{Collateral}}
$$
*Where $LB$ is Liquidation Bonus (e.g., 0.05).*

### C. Bad Debt Condition
Bad debt occurs when the value of collateral seized is less than the value of the debt repaid (insolvency of the position), usually due to the Liquidation Bonus exceeding the remaining equity.

$$
Value_{Collateral} < Value_{Debt} \implies \text{Bad Debt}
$$
Specifically, if $HF < \frac{1}{1 + LB}$, the position is effectively insolvent from the protocol's perspective if fully liquidated (Collateral value < Debt + Bonus).

---

## 5. Simulation Phases

### Phase 1: The Shock
*   Apply -30% price impact to ETH.
*   Update all user Health Factors.
*   Identify the set $S_{risky}$ of users where $HF < 1.0$.

### Phase 2: The Liquidation Cascade
*   Sort $S_{risky}$ by profitability (largest positions first).
*   **Step A:** Simulate liquidation of user $U_i$.
*   **Step B (Market Impact):** The liquidator sells seized ETH on DEXs.
    *   Calculate slippage based on "Stressed Market Liquidity" (20% depth).
    *   *Feedback Loop:* Selling ETH drives price down further.
    *   $Price_{ETH} = Price_{ETH} - \text{Slippage}(Volume_{sold})$.
*   **Step C:** Check if new price drop triggers more liquidations (Recursive).

### Phase 3: Evaluation
*   Sum total bad debt.
*   Calculate total liquidation volume vs. available market depth.

---

## 6. Outputs & Metrics

### Primary Metrics
1.  **Insolvency (Bad Debt):** Total USD value of debt not covered by collateral.
2.  **Positions Liquidated:**
    *   Count of Users.
    *   % of Total TVL liquidated.
3.  **Liquidation Volume:** Total ETH sold by liquidators.
4.  **Utilization Rate Spike:** Post-liquidation Utilization of the ETH reserve (did it hit 100%?).

### Visualizations (Suggested)
*   **Scatter Plot:** User Health Factor vs. Debt Size (Pre and Post Shock).
*   **Bar Chart:** Liquidatable Volume per Price Point ($100 drop buckets).
*   **Line Chart:** System Bad Debt Accumulation over the 6h window.

---

## 7. Stress vs. Worst-Case Distinction

*   **Stress Scenario (This Model):**
    *   30% Drop.
    *   Liquidators function but face slippage.
    *   Oracles work.
    *   *Result:* Measures protocol efficiency and parameter safety margins.

*   **Tail-Risk / Worst-Case (Out of Scope for this specific run):**
    *   50%+ Drop.
    *   Oracle Failure (Stale prices).
    *   Mempool clogging preventing liquidation transactions.
    *   *Result:* Measures catastrophic failure / insurance fund depletion.

---

## 8. Analytical Interpretation

**Risk Parameter Sensitivity:**
*   **Liquidation Threshold (LT):** If high (e.g., 90%), users have little buffer. A small drop causes massive liquidations.
*   **Liquidation Bonus (LB):** If high, it incentivizes liquidators but drains user equity faster, increasing bad debt risk if LTV is close to LT.

**Systemic Concentration:**
*   Identify if risk is concentrated in a few "Whales". If one large whale fails and slippage is high, they alone can cause bad debt.

---

## 9. Limitations

1.  **Behavioral Nuance:** Model assumes users do nothing. In reality, some would deposit more collateral or repay.
2.  **Cross-Chain Contagion:** Does not account for shocks originating on L2s (Arbitrum/Optimism) affecting Ethereum liquidity.
3.  **MEV/Front-running:** Complex gas wars between liquidators are simplified to "first profitable liquidator wins".
4.  **Off-chain Liquidity:** Assumes liquidators sell on-chain (Uniswap/Curve). It ignores CEX hedging (Binance/Coinbase), which might offer better liquidity.
