import pandas as pd
import numpy as np
import matplotlib.pyplot as plt
import copy

# --- Configuration & Constants ---

class ReserveConfig:
    def __init__(self, name, price, lt, ltv, lb, decimals=18):
        self.name = name
        self.price = price
        self.lt = lt       # Liquidation Threshold (e.g., 0.825)
        self.ltv = ltv     # Loan to Value (e.g., 0.80)
        self.lb = lb       # Liquidation Bonus (e.g., 0.05)
        self.decimals = decimals

class SimulationConfig:
    def __init__(self):
        self.eth_price_drop = 0.30          # 30% drop
        self.market_liquidity_depth = 2e6   # $2M depth for 1% slippage (simplified model)
        self.gas_cost_usd = 50.0            # Estimated gas cost for liquidation
        self.num_users = 1000
        self.whale_concentration = 0.01     # Top 1% are whales

# --- Core Logic Classes ---

class User:
    def __init__(self, uid, eth_collateral, usdc_debt):
        self.uid = uid
        self.eth_collateral = eth_collateral
        self.usdc_debt = usdc_debt
        self.initial_eth = eth_collateral
        self.initial_debt = usdc_debt
        self.is_liquidated = False
        self.bad_debt = 0.0

    def calculate_hf(self, eth_reserve):
        if self.usdc_debt == 0:
            return float('inf')
        
        collateral_value_eth = self.eth_collateral * eth_reserve.price
        # liquidation threshold applies to collateral
        collateral_risk_adjusted = collateral_value_eth * eth_reserve.lt
        
        # Health Factor = (Total Collateral in ETH * LT) / Total Debt in ETH
        # Note: Debt is USDC, so we convert USDC to ETH value or just compare USD values
        # HF = (Collateral_USD * LT) / Debt_USD
        
        collateral_usd = self.eth_collateral * eth_reserve.price
        debt_usd = self.usdc_debt # USDC price is 1
        
        if debt_usd == 0:
            return float('inf')
            
        return (collateral_usd * eth_reserve.lt) / debt_usd

    def get_state(self, eth_reserve):
        hf = self.calculate_hf(eth_reserve)
        collateral_usd = self.eth_collateral * eth_reserve.price
        debt_usd = self.usdc_debt
        return {
            "uid": self.uid,
            "hf": hf,
            "collateral_eth": self.eth_collateral,
            "collateral_usd": collateral_usd,
            "debt_usd": debt_usd,
            "bad_debt": self.bad_debt
        }

# --- Simulation Engine ---

class StressTestSimulation:
    def __init__(self):
        self.config = SimulationConfig()
        # Setup Reserves
        self.eth_reserve = ReserveConfig("ETH", 2000.0, 0.825, 0.80, 0.05) # Start at $2000
        self.users = []
        self.history = []
        
    def generate_users(self):
        print(f"Generating {self.config.num_users} users...")
        np.random.seed(42) # Reproducibility
        
        for i in range(self.config.num_users):
            is_whale = i < (self.config.num_users * self.config.whale_concentration)
            
            if is_whale:
                # Whales: Large positions, generally safer HF (1.5 - 2.0) but massive size
                eth_amt = np.random.uniform(1000, 10000) 
                target_hf = np.random.uniform(1.2, 1.8)
            else:
                # Retail: Smaller positions, wider HF spread (1.01 - 2.5)
                eth_amt = np.random.exponential(10) # avg 10 ETH
                target_hf = np.random.uniform(1.01, 2.0)
                
            # Calculate Debt based on Target HF
            # HF = (Collateral_USD * LT) / Debt_USD
            # Debt_USD = (Collateral_USD * LT) / HF
            
            collateral_usd = eth_amt * self.eth_reserve.price
            max_borrow = collateral_usd * self.eth_reserve.lt
            debt_usd = max_borrow / target_hf
            
            self.users.append(User(i, eth_amt, debt_usd))
            
        print("Users generated.")

    def run_shock_phase(self):
        print("\n--- Phase 1: The Shock ---")
        original_price = self.eth_reserve.price
        self.eth_reserve.price = original_price * (1 - self.config.eth_price_drop)
        print(f"ETH Price dropped from ${original_price} to ${self.eth_reserve.price} (-{self.config.eth_price_drop*100}%)")
        
        # Log initial state post-shock
        self._snapshot_state("Post-Shock")

    def run_liquidation_cascade(self):
        print("\n--- Phase 2: Liquidation Cascade ---")
        
        round_num = 0
        total_liquidated_eth = 0
        
        while True:
            round_num += 1
            print(f"Processing Round {round_num}...")
            
            liquidatable_users = [u for u in self.users if u.calculate_hf(self.eth_reserve) < 1.0]
            
            if not liquidatable_users:
                print("No more liquidatable users.")
                break
                
            # Sort by profitability/size (simplified to size here, assuming larger = more profit)
            liquidatable_users.sort(key=lambda u: u.usdc_debt, reverse=True)
            
            round_liquidation_vol_eth = 0
            
            for user in liquidatable_users:
                # Liquidation Logic
                # Max 50% close factor usually
                close_factor = 0.5
                debt_to_cover = user.usdc_debt * close_factor
                
                # Check if 50% is enough to bring HF > 1? 
                # Actually, standard logic is just pay 50% of debt.
                # But if HF is very low, might need 100% (not modeled here, sticking to standard close factor)
                
                # Collateral to seize = (Debt_Paid * (1 + Bonus)) / Price_ETH
                bonus_multiplier = 1 + self.eth_reserve.lb
                collateral_to_seize_usd = debt_to_cover * bonus_multiplier
                collateral_to_seize_eth = collateral_to_seize_usd / self.eth_reserve.price
                
                # Check if user has enough collateral
                actual_seized_eth = 0
                bad_debt_accrued = 0
                
                if collateral_to_seize_eth > user.eth_collateral:
                    # Partial/Full Liquidation where collateral < required payout (Bad Debt)
                    # Liquidator takes all collateral
                    actual_seized_eth = user.eth_collateral
                    
                    # Value taken
                    value_taken = actual_seized_eth * self.eth_reserve.price
                    
                    # Debt paid? Liquidator won't pay more than they get - profit margin.
                    # In reality, this transaction fails. 
                    # But for stress test, we mark this as "Bad Debt" potential.
                    # Let's assume protocol insurance covers the gap or it remains as bad debt.
                    
                    # Remaining Debt after liquidation
                    # Effective debt paid = Value_Taken / (1+Bonus) -- liquidator breaks even logic?
                    # Let's simplify: User is wiped out.
                    remaining_debt = user.usdc_debt - (value_taken / bonus_multiplier) # Theoretical
                    user.bad_debt = max(0, remaining_debt) # Simplified bad debt calculation
                    
                    user.eth_collateral = 0
                    user.usdc_debt = 0 # Wiped
                    
                else:
                    # Normal Liquidation
                    actual_seized_eth = collateral_to_seize_eth
                    user.eth_collateral -= actual_seized_eth
                    user.usdc_debt -= debt_to_cover
                
                round_liquidation_vol_eth += actual_seized_eth
                
            # Apply Market Impact (Slippage)
            # Simple Linear Model: Price drops by X% for every Y volume sold
            # Config: 2M USD depth for 1% drop.
            
            liquidation_value_sold = round_liquidation_vol_eth * self.eth_reserve.price
            slippage_pct = (liquidation_value_sold / self.config.market_liquidity_depth) * 0.01
            
            # Cap slippage per round to realistic bounds? or let it crash.
            # Let's apply it.
            
            prev_price = self.eth_reserve.price
            self.eth_reserve.price = self.eth_reserve.price * (1 - slippage_pct)
            
            print(f"  Round {round_num}: Liquidated {len(liquidatable_users)} users.")
            print(f"  Volume Sold: ${liquidation_value_sold:,.2f} ({round_liquidation_vol_eth:.2f} ETH)")
            print(f"  Price Impact: -{slippage_pct*100:.4f}% (${prev_price:.2f} -> ${self.eth_reserve.price:.2f})")
            
            total_liquidated_eth += round_liquidation_vol_eth
            self._snapshot_state(f"Round {round_num}")
            
            if slippage_pct < 0.0001: # Convergence check
                print("Price impact negligible, cascade stopped.")
                break
                
        print(f"Total Liquidated ETH: {total_liquidated_eth:.2f}")

    def _snapshot_state(self, stage):
        # Capture aggregate metrics
        total_bad_debt = sum(u.bad_debt for u in self.users)
        liquidatable_cnt = sum(1 for u in self.users if u.calculate_hf(self.eth_reserve) < 1.0)
        total_collateral_usd = sum(u.eth_collateral * self.eth_reserve.price for u in self.users)
        
        self.history.append({
            "stage": stage,
            "eth_price": self.eth_reserve.price,
            "bad_debt": total_bad_debt,
            "liquidatable_users": liquidatable_cnt,
            "total_collateral_usd": total_collateral_usd
        })

    def run_evaluation(self):
        print("\n--- Phase 3: Evaluation ---")
        df = pd.DataFrame(self.history)
        print(df)
        
        # Plotting
        plt.figure(figsize=(10, 6))
        
        # Subplot 1: Price vs Bad Debt
        plt.subplot(2, 1, 1)
        plt.plot(df['stage'], df['eth_price'], marker='o', color='blue', label='ETH Price')
        plt.ylabel('ETH Price ($)')
        plt.title('Price Cascade & Bad Debt')
        plt.grid(True)
        
        ax2 = plt.gca().twinx()
        ax2.plot(df['stage'], df['bad_debt'], marker='x', color='red', label='Bad Debt ($)')
        ax2.set_ylabel('Bad Debt ($)', color='red')
        
        # Subplot 2: Liquidatable Users
        plt.subplot(2, 1, 2)
        plt.bar(df['stage'], df['liquidatable_users'], color='orange')
        plt.ylabel('Count of Vulnerable Users')
        plt.title('Insolvency Risk')
        
        plt.tight_layout()
        plt.savefig('simulation_results.png')
        print("Results saved to simulation_results.png")

        print("\n--- Final Results Summary ---")
        final_state = self.history[-1]
        print(f"Final ETH Price: ${final_state['eth_price']:.2f}")
        print(f"Total Bad Debt: ${final_state['bad_debt']:,.2f}")
        print(f"Total Collateral Remaining: ${final_state['total_collateral_usd']:,.2f}")
        print(f"Risk Status: {'CRITICAL' if final_state['bad_debt'] > 0 else 'STABLE'}")

# --- Run ---

if __name__ == "__main__":
    sim = StressTestSimulation()
    sim.generate_users()
    sim.run_shock_phase()
    sim.run_liquidation_cascade()
    sim.run_evaluation()
