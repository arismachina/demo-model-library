# Battery Energy Storage Duty Cycle Profiles - Documentation

## Overview
This dataset contains minute-resolution power profiles for six different battery energy storage duty cycles, based on published research and standardized protocols from national laboratories and academic institutions.

## Data Sources and References

### Primary Sources:
1. **DOE/Sandia/PNNL Protocol** (SAND2016-3078 R, PNNL-22010 Rev. 2)
   - "Protocol for Uniformly Measuring and Expressing the Performance of Energy Storage Systems"
   - Developed by Sandia National Laboratories and Pacific Northwest National Laboratory
   - Published April 2016

2. **TUM SimSES Open Data Profiles**
   - Technical University of Munich, Chair of Electrical Energy Storage Technology
   - Kucevic et al. (2020), "Standard battery energy storage system profiles"
   - Journal of Energy Storage, Volume 28
   - DOI: 10.14459/2019mp1510254

3. **PJM Frequency Regulation Data**
   - Rosewater & Ferreira (2016), "Development of a frequency regulation duty-cycle"
   - Journal of Energy Storage, Volume 6
   - Based on 2012 PJM regulation signal data (4-second timestep)

4. **Sandia PV Smoothing Protocol**
   - SAND2016-3474, "Determination of Duty Cycle for Energy Storage Systems in a PV Smoothing Application"
   - Schoenwald et al., 2016

## File Descriptions

### 1. frequency_regulation_duty_cycle.csv
- **Duration**: 1440 minutes (24 hours)
- **Resolution**: 1 minute
- **Application**: Grid frequency regulation (ancillary services)
- **Characteristics**:
  - High-frequency power oscillations (±1 per unit)
  - Energy neutral over 24-hour period
  - Multiple timescale components (5 min, 15 min, 60 min cycles)
  - Based on PJM regulation signal aggregated from 4-second to 1-minute resolution
- **Typical Annual Cycles**: 250-300 full equivalent cycles
- **Sign Convention**: Positive = discharge, Negative = charge

### 2. energy_time_shifting_duty_cycle.csv
- **Duration**: 1440 minutes (24 hours)
- **Resolution**: 1 minute
- **Application**: Solar + storage self-consumption / arbitrage
- **Characteristics**:
  - Daily charge cycle during solar generation (6 AM - 6 PM)
  - Peak charging at solar noon (12 PM)
  - Discharge during evening peak demand (5 PM - 10 PM)
  - One full charge-discharge cycle per day
- **Typical Annual Cycles**: 250-365 full equivalent cycles
- **Sign Convention**: Positive = charge, Negative = discharge

### 3. peak_shaving_duty_cycle.csv
- **Duration**: 1440 minutes (24 hours)
- **Resolution**: 1 minute
- **Application**: Commercial/industrial demand charge reduction
- **Characteristics**:
  - Targeted discharge during peak demand periods only
  - Three discharge events: morning (8-10 AM), midday (11 AM-2 PM), evening (5-8 PM)
  - Overnight charging during low-demand periods (1-6 AM)
  - Strongest discharge during evening peak
- **Typical Annual Cycles**: 150-250 full equivalent cycles
- **Sign Convention**: Positive = charge, Negative = discharge

### 4. capacity_firming_duty_cycle.csv
- **Duration**: 720 minutes (12 hours daylight)
- **Resolution**: 1 minute
- **Application**: PV output smoothing / renewable firming
- **Characteristics**:
  - Irregular cycling based on cloud transients
  - Multiple cloud events (15-45 minute duration each)
  - High-frequency variability overlaid on base solar profile
  - Battery compensates for solar intermittency
  - Based on Sandia PV Smoothing protocol (30-minute moving average filter)
- **Typical Annual Cycles**: 100-200 full equivalent cycles
- **Cycle Depth**: Typically shallow (20-40% DOD)
- **Sign Convention**: Positive = charge, Negative = discharge

### 5. backup_power_duty_cycle.csv
- **Duration**: 2880 minutes (48 hours)
- **Resolution**: 1 minute
- **Application**: Emergency backup / black start capability
- **Characteristics**:
  - Extended idle period during normal grid operation (first 24h)
  - Grid outage event at hour 24
  - Sustained deep discharge for 12 hours during outage
  - Gradual battery depletion (90% to 50% power output)
  - Recharge period after grid restoration (6 hours)
- **Typical Annual Cycles**: <10 full equivalent cycles (rare events)
- **Cycle Depth**: Deep discharge (80-100% DOD)
- **Sign Convention**: Positive = charge, Negative = discharge

### 6. renewable_shifting_duty_cycle.csv
- **Duration**: 10080 minutes (1 week)
- **Resolution**: 1 minute
- **Application**: Seasonal/weekly renewable energy storage
- **Characteristics**:
  - Daily charging during solar generation (8 AM - 4 PM)
  - Evening discharge (6-10 PM)
  - Weekend variation (20% higher solar availability)
  - Weekly energy balancing pattern
  - Longer duration storage compared to daily arbitrage
- **Typical Annual Cycles**: 50-100 full equivalent cycles
- **Sign Convention**: Positive = charge, Negative = discharge

## Technical Specifications

### Power Units
All power values are normalized to per-unit (p.u.) values relative to the battery system's rated power:
- **1.0 p.u.** = 100% of rated power
- **0.5 p.u.** = 50% of rated power
- **Positive values** = Charging (for most applications, see sign conventions)
- **Negative values** = Discharging

### Data Format
```
Time_Minutes,Power_PerUnit,Description
0,-0.1234,Application-specific description
1,0.5678,...
```

### Key Performance Metrics
Based on SimSES profile analysis framework, these profiles can be characterized by:
1. **Full Equivalent Cycles (FEC)**: Total annual energy throughput
2. **Efficiency**: Round-trip energy efficiency (typically 83-93%)
3. **Depth of Discharge (DOD)**: Typical cycle depth
4. **Number of Sign Changes**: Charge/discharge transitions per day
5. **Resting Periods**: Duration between active cycles
6. **Energy Between Sign Changes**: Energy throughput per cycle

## Usage Guidelines

### Scaling to Actual Systems
To convert per-unit power to actual power (kW or MW):
```
Actual_Power (kW) = Power_PerUnit × Rated_Power (kW)
```

### Energy Calculation
```
Energy (kWh) = ∫ Power (kW) × dt (hours)
```

For minute-resolution data:
```
Energy (kWh) = Σ [Power (kW) × (1/60)]
```

### State of Charge (SOC) Estimation
```
SOC(t) = SOC(0) + ∫[0 to t] (Power/Capacity) × η × dt
```
Where:
- SOC(0) = Initial state of charge
- Capacity = Rated energy capacity (kWh)
- η = Efficiency (charge or discharge)

## Validation and Comparison

These profiles align with published characteristics:

| Application | Annual FEC | Efficiency | Reference |
|-------------|-----------|------------|-----------|
| Frequency Regulation | 250-300 | 85-90% | DOE Protocol |
| Energy Time-Shifting | 250-365 | 87-92% | SimSES |
| Peak Shaving | 150-250 | 88-93% | SimSES |
| PV Smoothing | 100-200 | 85-90% | Sandia |
| Backup Power | <10 | 80-85% | Literature |
| Renewable Shifting | 50-100 | 88-92% | SimSES |

## Limitations

1. **Synthetic Data**: Profiles are generated based on published characteristics and methodologies, not direct measurements
2. **Idealized Conditions**: Do not include real-world variations like equipment failures, maintenance, or market curtailment
3. **No Aging Effects**: Power profiles assume constant performance (no degradation over time)
4. **Simplified Models**: Actual systems may have more complex control strategies
5. **Regional Variations**: Actual duty cycles vary by geographic location, market rules, and grid conditions

## Applications

These profiles can be used for:
- Battery lifetime testing and prediction
- Techno-economic analysis of storage projects
- Comparison of different battery chemistries
- Energy management system (EMS) development
- Sizing and design optimization
- Degradation modeling and validation
- Performance benchmarking

## Additional Resources

### Open Data Sources:
- **TUM SimSES Profiles**: https://mediatum.ub.tum.de/1510254 (5.2 GB dataset)
- **SimSES Software**: https://gitlab.lrz.de/open-ees-ses/simses
- **DOE Protocol**: https://www.pnnl.gov/main/publications/external/technical_reports/PNNL-22010Rev2.pdf

### Related Publications:
- Kucevic, D., et al. (2020). "Standard battery energy storage system profiles." Journal of Energy Storage, 28, 101077.
- Rosewater, D., & Ferreira, S. (2016). "Development of a frequency regulation duty-cycle." Journal of Energy Storage, 6, 103-112.
- Möller, M., et al. (2022). "SimSES: A holistic simulation framework." Journal of Energy Storage, 49, 103743.

## Citation

If you use these profiles in your work, please cite:
1. The relevant DOE Protocol (SAND2016-3078 R)
2. The SimSES framework (Kucevic et al., 2020)
3. The specific application duty cycle source (see references above)

## Contact and Feedback

These profiles are based on published methodologies and open research. For questions about:
- **DOE Protocol**: Contact Sandia National Laboratories ESS Program
- **SimSES Profiles**: Contact TUM Chair of Electrical Energy Storage (simses.ees@ei.tum.de)
- **This Dataset**: Generated January 2026 based on published literature

## Version History
- **v1.0** (January 2026): Initial release with 6 duty cycle profiles at 1-minute resolution

## License
These profiles are generated based on publicly available research and methodologies. The original sources have various licenses (see individual publications). This derivative work is provided for research and educational purposes.
