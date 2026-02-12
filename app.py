import streamlit as st
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
    def __init__(self, eth_price_drop, market_liquidity_depth, num_users, whale_concentration, start_price):
        self.eth_price_drop = eth_price_drop
        self.market_liquidity_depth = market_liquidity_depth
        self.num_users = num_users
        self.whale_concentration = whale_concentration
        self.start_price = start_price

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
        
        collateral_usd = self.eth_collateral * eth_reserve.price
        debt_usd = self.usdc_debt
        
        if debt_usd == 0:
            return float('inf')
            
        return (collateral_usd * eth_reserve.lt) / debt_usd

# --- Simulation Engine ---

class StressTestSimulation:
    def __init__(self, config):
        self.config = config
        # Setup Reserves
        self.eth_reserve = ReserveConfig("ETH", config.start_price, 0.825, 0.80, 0.05)
        self.users = []
        self.history = []
        self.logs = []
        
    def log(self, message):
        self.logs.append(message)

    def generate_users(self):
        np.random.seed(42) # Reproducibility
        
        for i in range(self.config.num_users):
            is_whale = i < (self.config.num_users * self.config.whale_concentration)
            
            if is_whale:
                eth_amt = np.random.uniform(1000, 10000) 
                target_hf = np.random.uniform(1.2, 1.8)
            else:
                eth_amt = np.random.exponential(10) 
                target_hf = np.random.uniform(1.01, 2.0)
                
            collateral_usd = eth_amt * self.eth_reserve.price
            max_borrow = collateral_usd * self.eth_reserve.lt
            debt_usd = max_borrow / target_hf
            
            self.users.append(User(i, eth_amt, debt_usd))

    def run(self):
        # Initial State
        self.generate_users()
        
        # Phase 1: Shock
        original_price = self.eth_reserve.price
        self.eth_reserve.price = original_price * (1 - self.config.eth_price_drop)
        self.log(f"Phase 1: Shock - ETH Price dropped from ${original_price} to ${self.eth_reserve.price:.2f} (-{self.config.eth_price_drop*100}%)")
        self._snapshot_state("Post-Shock")

        # Phase 2: Liquidation Cascade
        round_num = 0
        total_liquidated_eth = 0
        
        while True:
            round_num += 1
            liquidatable_users = [u for u in self.users if u.calculate_hf(self.eth_reserve) < 1.0]
            
            if not liquidatable_users:
                break
                
            liquidatable_users.sort(key=lambda u: u.usdc_debt, reverse=True)
            round_liquidation_vol_eth = 0
            
            for user in liquidatable_users:
                close_factor = 0.5
                debt_to_cover = user.usdc_debt * close_factor
                bonus_multiplier = 1 + self.eth_reserve.lb
                collateral_to_seize_usd = debt_to_cover * bonus_multiplier
                collateral_to_seize_eth = collateral_to_seize_usd / self.eth_reserve.price
                
                actual_seized_eth = 0
                
                if collateral_to_seize_eth > user.eth_collateral:
                    actual_seized_eth = user.eth_collateral
                    value_taken = actual_seized_eth * self.eth_reserve.price
                    remaining_debt = user.usdc_debt - (value_taken / bonus_multiplier)
                    user.bad_debt = max(0, remaining_debt)
                    user.eth_collateral = 0
                    user.usdc_debt = 0
                else:
                    actual_seized_eth = collateral_to_seize_eth
                    user.eth_collateral -= actual_seized_eth
                    user.usdc_debt -= debt_to_cover
                
                round_liquidation_vol_eth += actual_seized_eth
                
            liquidation_value_sold = round_liquidation_vol_eth * self.eth_reserve.price
            slippage_pct = (liquidation_value_sold / self.config.market_liquidity_depth) * 0.01
            
            prev_price = self.eth_reserve.price
            self.eth_reserve.price = self.eth_reserve.price * (1 - slippage_pct)
            
            self.log(f"Round {round_num}: Liquidated {len(liquidatable_users)} users. Volume: {round_liquidation_vol_eth:.2f} ETH. Price Impact: -{slippage_pct*100:.4f}%")
            
            total_liquidated_eth += round_liquidation_vol_eth
            self._snapshot_state(f"Round {round_num}")
            
            if slippage_pct < 0.0001:
                break
                
        return pd.DataFrame(self.history), self.logs

    def _snapshot_state(self, stage):
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

# --- Streamlit UI ---

st.set_page_config(page_title="Aave V3 Stress Simulator", layout="wide")

st.title("Aave V3 Stress-Test Simulator")
st.markdown("""
This tool simulates a **liquidation cascade** on Aave V3 (Ethereum) under stress conditions.
Adjust the parameters in the sidebar to test different scenarios.
""")

# Sidebar Controls
st.sidebar.header("Simulation Parameters")

eth_price_drop = st.sidebar.slider("Initial ETH Price Drop (%)", 0.0, 0.90, 0.30, 0.05)
market_liquidity = st.sidebar.number_input("Market Liquidity Depth ($ for 1% slippage)", value=2_000_000, step=500_000)
num_users = st.sidebar.number_input("Number of Users", value=1000, step=100)
whale_concentration = st.sidebar.slider("Whale Concentration (Top %)", 0.0, 0.10, 0.01, 0.001)
start_price = st.sidebar.number_input("Starting ETH Price ($)", value=2000.0)

# Run Simulation
# Automatically run simulation when parameters change
config = SimulationConfig(
    eth_price_drop=eth_price_drop,
    market_liquidity_depth=market_liquidity,
    num_users=num_users,
    whale_concentration=whale_concentration,
    start_price=start_price
)

sim = StressTestSimulation(config)

with st.spinner('Running simulation...'):
    df_results, logs = sim.run()

# Results Section
st.divider()

# Key Metrics
final_state = df_results.iloc[-1]
col1, col2, col3, col4 = st.columns(4)

col1.metric("Final ETH Price", f"${final_state['eth_price']:.2f}", delta=f"{((final_state['eth_price']/start_price)-1)*100:.1f}%")
col2.metric("Total Bad Debt", f"${final_state['bad_debt']:,.2f}", delta_color="inverse")
col3.metric("Vulnerable Users", f"{int(final_state['liquidatable_users'])}")
col4.metric("Risk Status", "CRITICAL" if final_state['bad_debt'] > 0 else "STABLE", 
            delta_color="inverse" if final_state['bad_debt'] > 0 else "normal")

# Charts
st.subheader("Liquidation Cascade Analysis")

chart_col1, chart_col2 = st.columns(2)

with chart_col1:
    st.caption("ETH Price vs Bad Debt Accumulation")
    # Custom Plot
    fig, ax1 = plt.subplots()
    ax1.plot(df_results['stage'], df_results['eth_price'], 'b-o', label='ETH Price')
    ax1.set_xlabel('Simulation Stage')
    ax1.set_ylabel('ETH Price ($)', color='b')
    ax1.tick_params(axis='y', labelcolor='b')
    plt.xticks(rotation=45)
    
    ax2 = ax1.twinx()
    ax2.plot(df_results['stage'], df_results['bad_debt'], 'r-x', label='Bad Debt')
    ax2.set_ylabel('Bad Debt ($)', color='r')
    ax2.tick_params(axis='y', labelcolor='r')
    st.pyplot(fig)

with chart_col2:
    st.caption("Collateral Value Remaining")
    st.bar_chart(df_results.set_index('stage')['total_collateral_usd'])

# Detailed Data
with st.expander("View Simulation Logs"):
    for log in logs:
        st.text(log)
        
with st.expander("View Raw Data"):
    st.dataframe(df_results)
