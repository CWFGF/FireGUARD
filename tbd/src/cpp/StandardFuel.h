/* Copyright (c) Queen's Printer for Ontario, 2020. */
/* Copyright (c) His Majesty the King in Right of Canada as represented by the Minister of Natural Resources, 2021-2024. */

/* SPDX-License-Identifier: AGPL-3.0-or-later */

#pragma once
#include "FireSpread.h"
#include "FuelType.h"
#include "LookupTable.h"
namespace tbd
{
using sim::SpreadInfo;
namespace fuel
{
/**
 * \brief Limit to slope when calculating ISI
 */
static constexpr MathSize SLOPE_LIMIT_ISI = 0.01;
/**
 * \brief Calculate standard foliar moisture effect (FME) based on FMC [ST-X-3 eq 61]
 * \param fmc Foliar Moisture Content (FMC)
 * \return Standard foliar moisture effect (FME) based on FMC [ST-X-3 eq 61]
 */
[[nodiscard]] static constexpr MathSize
  calculate_standard_foliar_moisture_fmc(
    const MathSize fmc) noexcept
{
  return util::pow_int<4>(1.5 - 0.00275 * fmc) / (460.0 + 25.9 * fmc) / 0.778 * 1000.0;
}
/**
 * \brief Standard foliar moisture effect (FME) based on FMC [ST-X-3 eq 61]
 */
static const util::LookupTable<&calculate_standard_foliar_moisture_fmc>
  STANDARD_FOLIAR_MOISTURE_FMC{};
/**
 * \brief Crown fire spread rate (m/min) / Foliar Moisture Effect (RSC / (FME / FME_avg)) [ST-X-3 eq 64]
 * \param isi Initial Spread Index
 * \return RSC / (FME / FME_avg) [ST-X-3 eq 64]
 */
[[nodiscard]] static MathSize
  calculate_standard_foliar_moisture_isi(
    const MathSize isi) noexcept
{
  return 60.0 * (1.0 - exp(-0.0497 * isi));
}
/**
 * \brief Crown fire spread rate (m/min) / Foliar Moisture Effect (RSC / (FME / FME_avg)) [ST-X-3 eq 64]
 * \return RSC / (FME / FME_avg) [ST-X-3 eq 64]
 */
static const util::LookupTable<&calculate_standard_foliar_moisture_isi>
  STANDARD_FOLIAR_MOISTURE_ISI{};
/**
 * \brief Length to Breadth ratio [ST-X-3 eq 79]
 * \param ws Wind Speed (km/h)
 * \return Length to Breadth ratio [ST-X-3 eq 79]
 */
[[nodiscard]] static MathSize
  calculate_standard_length_to_breadth(const MathSize ws) noexcept
{
  return 1.0 + 8.729 * pow(1.0 - exp(-0.030 * ws), 2.155);
}
/**
 * \brief Length to Breadth ratio [ST-X-3 eq 79]
 * \return Length to Breadth ratio [ST-X-3 eq 79]
 */
static const util::LookupTable<&calculate_standard_length_to_breadth>
  STANDARD_LENGTH_TO_BREADTH{};
/**
 * \brief A FuelBase made of a standard fuel type.
 * \tparam A Rate of spread parameter a [ST-X-3 table 6]
 * \tparam B Rate of spread parameter b * 10000 [ST-X-3 table 6]
 * \tparam C Rate of spread parameter c * 100 [ST-X-3 table 6]
 * \tparam Bui0 Average Build-up Index for the fuel type [ST-X-3 table 7]
 * \tparam Cbh Crown base height (m) [ST-X-3 table 8]
 * \tparam Cfl Crown fuel load (kg/m^2) [ST-X-3 table 8]
 * \tparam BulkDensity Duff Bulk Density (kg/m^3) [Anderson table 1] * 1000
 * \tparam InorganicPercent Inorganic percent of Duff layer (%) [Anderson table 1]
 * \tparam DuffDepth Depth of Duff layer (cm * 10) [Anderson table 1]
 */
template <int A, int B, int C, int Bui0, int Cbh, int Cfl, int BulkDensity, int InorganicPercent, int DuffDepth>
class StandardFuel
  : public FuelBase<BulkDensity, InorganicPercent, DuffDepth>
{
public:
  /**
   * \brief Constructor
   * \param code Code to identify fuel with
   * \param name Name of the fuel
   * \param can_crown Whether or not this fuel type can have a crown fire
   * \param log_q Log value of q [ST-X-3 table 7]
   * \param duff_ffmc Type of duff near the surface
   * \param duff_dmc Type of duff deeper underground
   */
  constexpr StandardFuel(const FuelCodeSize& code,
                         const char* name,
                         const bool can_crown,
                         const LogValue log_q,
                         const Duff* duff_ffmc,
                         const Duff* duff_dmc) noexcept
    : FuelBase<BulkDensity, InorganicPercent, DuffDepth>(code,
                                                         name,
                                                         can_crown,
                                                         duff_ffmc,
                                                         duff_dmc),
      log_q_(log_q)
  {
  }
  /**
   * \brief Constructor
   * \param code Code to identify fuel with
   * \param name Name of the fuel
   * \param can_crown Whether or not this fuel type can have a crown fire
   * \param log_q Log value of q [ST-X-3 table 7]
   * \param duff Type of duff near the surface and deeper underground
   */
  constexpr StandardFuel(const FuelCodeSize& code,
                         const char* name,
                         const bool can_crown,
                         const LogValue log_q,
                         const Duff* duff) noexcept
    : StandardFuel(code,
                   name,
                   can_crown,
                   log_q,
                   duff,
                   duff)
  {
  }
  StandardFuel(StandardFuel&& rhs) noexcept = delete;
  StandardFuel(const StandardFuel& rhs) noexcept = delete;
  StandardFuel& operator=(StandardFuel&& rhs) noexcept = delete;
  StandardFuel& operator=(const StandardFuel& rhs) = delete;
  /**
   * \brief Initial rate of spread (m/min) [ST-X-3 eq 26]
   * \param isi Initial Spread Index
   * \return Initial rate of spread (m/min) [ST-X-3 eq 26]
   */
  [[nodiscard]] MathSize rosBasic(const MathSize isi) const noexcept
  {
    return a() * pow(1.0 - exp(negB() * isi), c());
  }
  virtual /**
           * \brief Crown Fuel Consumption (CFC) (kg/m^2) [ST-X-3 eq 66]
           * \param cfb Crown Fraction Burned (CFB) [ST-X-3 eq 58]
           * \return Crown Fuel Consumption (CFC) (kg/m^2) [ST-X-3 eq 66]
           */
    MathSize
    crownConsumption(const MathSize cfb) const noexcept override
  {
    return cfl() * cfb;
  }
  /**
   * \brief ISI with slope influence and zero wind (ISF) [ST-X-3 eq 41]
   * \param mu Multiplier
   * \param rsf Slope-adjusted zero wind rate of spread (RSF) [ST-X-3 eq 40]
   * \return ISI with slope influence and zero wind (ISF) [ST-X-3 eq 41]
   */
  [[nodiscard]] MathSize limitIsf(const MathSize mu, const MathSize rsf) const noexcept
  {
    return (1.0 / negB()) * log(max(SLOPE_LIMIT_ISI, (rsf > 0.0) ? (1.0 - pow((rsf / (mu * a())), (1.0 / c()))) : 1.0));
  }
  /**
   * \brief Critical Surface Fire Intensity (CSI) [ST-X-3 eq 56]
   * \param spread SpreadInfo to use in calculation
   * \return Critical Surface Fire Intensity (CSI) [ST-X-3 eq 56]
   */
  [[nodiscard]] MathSize criticalSurfaceIntensity(const SpreadInfo& spread) const noexcept
    override
  {
    return 0.001 * pow(cbh(), 1.5) * pow(460.0 + 25.9 * spread.foliarMoisture(), 1.5);
  }
  /**
   * \brief Length to Breadth ratio [ST-X-3 eq 79]
   * \param ws Wind Speed (km/h)
   * \return Length to Breadth ratio [ST-X-3 eq 79]
   */
  [[nodiscard]] MathSize lengthToBreadth(const MathSize ws) const noexcept override
  {
    return STANDARD_LENGTH_TO_BREADTH(ws);
  }
  /**
   * \brief Final rate of spread (m/min)
   * \param rss Surface Rate of spread (ROS) (m/min) [ST-X-3 eq 55]
   * \return Final rate of spread (m/min)
   */
  MathSize finalRos(const SpreadInfo&,
                    MathSize,
                    MathSize,
                    const MathSize rss) const noexcept override
  {
    return rss;
  }
  /**
   * \brief BUI Effect on surface fire rate of spread [ST-X-3 eq 54]
   * \param bui Build-up Index
   * \return BUI Effect on surface fire rate of spread [ST-X-3 eq 54]
   */
  [[nodiscard]] MathSize buiEffect(const MathSize bui) const noexcept override
  {
    return (0 < bui)
           ? exp(
               50.0
               * log_q_.asValue()
               * ((1.0 / bui) - (1.0 / bui0())))
           : 1.0;
  }
protected:
  ~StandardFuel() = default;
  /**
   * \brief Average Build-up Index for the fuel type [ST-X-3 table 7]
   * \return Average Build-up Index for the fuel type [ST-X-3 table 7]
   */
  [[nodiscard]] static constexpr MathSize bui0() noexcept
  {
    return Bui0;
  }
  /**
   * \brief Crown base height (m) [ST-X-3 table 8]
   * \return Crown base height (m) [ST-X-3 table 8]
   */
  [[nodiscard]] MathSize cbh() const override
  {
    return Cbh;
  }
  /**
   * \brief Crown fuel load (kg/m^2) [ST-X-3 table 8]
   * \return Crown fuel load (kg/m^2) [ST-X-3 table 8]
   */
  [[nodiscard]] MathSize cfl() const override
  {
    return Cfl / 100.0;
  }
  /**
   * \brief Rate of spread parameter a [ST-X-3 table 6]
   * \return Rate of spread parameter a [ST-X-3 table 6]
   */
  [[nodiscard]] static constexpr MathSize a() noexcept
  {
    return A;
  }
  /**
   * \brief Negative of rate of spread parameter b [ST-X-3 table 6]
   * \return Negative of rate of spread parameter b [ST-X-3 table 6]
   */
  [[nodiscard]] static constexpr MathSize negB() noexcept
  {
    // the only places this gets used it gets negated so just store it that way
    return -B / 10000.0;
  }
  /**
   * \brief Rate of spread parameter c [ST-X-3 table 6]
   * \return Rate of spread parameter c [ST-X-3 table 6]
   */
  [[nodiscard]] static constexpr MathSize c() noexcept
  {
    return C / 100.0;
  }
  /**
   * \brief Crown fire spread rate (RSC) (m/min) [ST-X-3 eq 64]
   * \param isi Initial Spread Index
   * \param fmc Foliar Moisture Content
   * \return Crown fire spread rate (RSC) (m/min) [ST-X-3 eq 64]
   */
  [[nodiscard]] static constexpr MathSize crownRateOfSpread(const MathSize isi,
                                                            const MathSize fmc) noexcept
  {
    return STANDARD_FOLIAR_MOISTURE_ISI(isi) * STANDARD_FOLIAR_MOISTURE_FMC(fmc);
  }
private:
  /**
   * \brief Log value of q [ST-X-3 table 7]
   */
  LogValue log_q_;
  static_assert(-negB() < 1);
  static_assert(c() < 10 && c() > 1);
};
}
}
