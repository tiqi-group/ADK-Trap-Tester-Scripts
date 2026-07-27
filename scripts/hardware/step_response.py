
import numpy as np
import pandas as pd
import matplotlib.pyplot as plt

def step_double_rc(x, c1, c2, r1, r2, V_end):
    tau1 = r1 * c1
    tau2 = r2 * c2
    tau3 = r1 * c2
    T = np.sqrt(tau1**2 - 2*tau1 * (tau2 - tau3) + tau2**2 + 2 * tau2 * tau3 + tau3**2)

    exp1 = T / (tau1*tau2)
    exp2 = -(1 + (T + tau2 + tau3) / tau1) / 2.0 / tau2

    term1 = (tau2 - tau3 - tau1 + T) / 2.0 / T * np.exp(x * exp2)
    term2 = (tau1 - tau2 + tau3 + T) / 2.0 / T * np.exp(x * (exp1 + exp2))

    return V_end * (1 - (term1 + term2))


c1 = 0.5e-9
c2 = 1e-9
r1 = 10470
r2 = 5000
V_end = 2

t = np.linspace(0, 0.20e-3, 1000)
v_meas = step_double_rc(V_end, t, c1, c2, r1, r2)

df = pd.read_csv('step_response.txt', delimiter='\t')
t_sim = df['time']
v_sim = df['V(v_out)']

plt.plot(t* 1e6, v_meas)
plt.plot(t_sim*1e6, v_sim) 
plt.show()
