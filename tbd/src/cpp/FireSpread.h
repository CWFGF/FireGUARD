/* Copyright (c) Queen's Printer for Ontario, 2020. */
/* Copyright (c) His Majesty the King in Right of Canada as represented by the Minister of Natural Resources, 2021-2024. */

/* SPDX-License-Identifier: AGPL-3.0-or-later */

#pragma once
#include "Cell.h"
#include "FWI.h"
#include "Point.h"
#include "Settings.h"
#include "Util.h"
#include "InnerPos.h"
namespace tbd::sim
{

static constexpr int MAX_SPREAD_ANGLE = 5.0;
static constexpr MathSize INVALID_ROS = -1.0;
static constexpr MathSize INVALID_INTENSITY = -1.0;

class Scenario;
/**
 * \brief Possible results of an attempt to spread.
 */
int calculate_nd_ref_for_point(const int elevation, const topo::Point& point) noexcept;
int calculate_nd_for_point(const Day day, const int elevation, const topo::Point& point);
/**
 * \brief Information regarding spread within a Cell for a specific Scenario and time.
 */
class SpreadInfo
{
public:
  /**
   * \brief Lookup table for Slope Factor calculated from Percent Slope
   */
  static const SlopeTableArray SlopeTable;
  ~SpreadInfo() = default;
  SpreadInfo(const Scenario& scenario,
             DurationSize time,
             const topo::SpreadKey& key,
             int nd,
             const wx::FwiWeather* weather);
  /**
   * \brief Calculate fire spread for time and place
   * \param scenario Scenario this is spreading in
   * \param time Time spread is occurring
   * \param key Attributes for Cell spread is occurring in
   * \param nd Difference between date and the date of minimum foliar moisture content
   * \param weather FwiWeather to use for calculations
   */
  SpreadInfo(const Scenario& scenario,
             DurationSize time,
             const topo::SpreadKey& key,
             int nd,
             const wx::FwiWeather* weather,
             const wx::FwiWeather* weather_daily);
  constexpr SpreadInfo(SpreadInfo&& rhs) noexcept = default;
  SpreadInfo(const SpreadInfo& rhs) noexcept = default;
  constexpr SpreadInfo& operator=(SpreadInfo&& rhs) noexcept = default;
  SpreadInfo& operator=(const SpreadInfo& rhs) noexcept = default;
  // static MathSize calculateSpreadProbability(MathSize ros);
  /**
   * \brief Determine rate of spread from probability of spread threshold
   * \param threshold Probability of spread threshold
   * \return Rate of spread at given threshold (m/min)
   */
  [[nodiscard]] static constexpr MathSize calculateRosFromThreshold(const ThresholdSize threshold)
  {
    // for some reason it returns -nan instead of nan if it's 1, so return this instead
    if (1.0 == threshold)
    {
      return std::numeric_limits<ThresholdSize>::infinity();
    }
    if (0.0 == threshold)
    {
      return 0.0;
    }
    // NOTE: based off spread event probability from wotton
    // should be the inverse of calculateSpreadProbability()
    return 25.0 / 4.0 * log(-(exp(41.0 / 25.0) * threshold) / (threshold - 1));
  }
  /**
   * \brief Maximum intensity in any direction for spread (kW/m)
   * \return Maximum intensity in any direction for spread (kW/m)
   */
  [[nodiscard]] MathSize maxIntensity() const noexcept
  {
    return max_intensity_;
  }
  /**
   * \brief Offsets from origin point that represent spread under these conditions
   * \return Offsets from origin point that represent spread under these conditions
   */
  [[nodiscard]] const OffsetSet& offsets() const
  {
    return offsets_;
  }
  /**
   * \brief Whether or not there is no spread
   * \return Whether or not there is no spread
   */
  [[nodiscard]] constexpr bool isNotSpreading() const
  {
    return isInvalid();
  }
  /**
   * \brief Difference between date and the date of minimum foliar moisture content
   * \return Difference between date and the date of minimum foliar moisture content
   */
  [[nodiscard]] constexpr int nd() const
  {
    return nd_;
  }
  /**
   * \brief FwiWeather used for spread
   * \return FwiWeather used for spread
   */
  [[nodiscard]] constexpr const wx::FwiWeather* weather() const
  {
    return weather_;
  }
  /**
   * \brief Wind used for spread
   * \return Wind used for spread
   */
  [[nodiscard]] constexpr const wx::Wind& wind() const
  {
    return weather()->wind();
  }
  /**
   * \brief Fine Fuel Moisture Code used for spread
   * \return Fine Fuel Moisture Code used for spread
   */
  [[nodiscard]] constexpr const wx::Ffmc& ffmc() const
  {
    return weather()->ffmc();
  }
  /**
   * \brief Build-up Index used for spread
   * \return Build-up Index used for spread
   */
  [[nodiscard]] constexpr const wx::Bui& bui() const
  {
    return weather()->bui();
  }
  /**
   * \brief Duff Moisture Code used for spread
   * \return Duff Moisture Code used for spread
   */
  [[nodiscard]] constexpr const wx::Dmc& dmc() const
  {
    return weather()->dmc();
  }
  /**
   * \brief Drought Code used for spread
   * \return Drought Code used for spread
   */
  [[nodiscard]] constexpr const wx::Dc& dc() const
  {
    return weather()->dc();
  }
  /**
   * \brief FFMC effect used for spread
   * \return FFMC effect used for spread
   */
  [[nodiscard]] constexpr MathSize ffmcEffect() const
  {
    return weather()->ffmcEffect();
  }
  /**
   * \brief Time used for spread
   * \return Time used for spread
   */
  [[nodiscard]] constexpr DurationSize time() const
  {
    return time_;
  }
  /**
   * \brief Length to breadth ratio used for spread
   * \return Length to breadth ratio used for spread
   */
  [[nodiscard]] constexpr MathSize lengthToBreadth() const
  {
    return l_b_;
  }
  /**
   * \brief Slope used for spread (%)
   * \return Slope used for spread (%)
   */
  [[nodiscard]] constexpr SlopeSize percentSlope() const
  {
    return topo::Cell::slope(key_);
  }
  /**
   * \brief Aspect used for spread (degrees)
   * \return Aspect used for spread (degrees)
   */
  [[nodiscard]] constexpr AspectSize slopeAzimuth() const
  {
    return topo::Cell::aspect(key_);
  }
  /**
   * \brief Head fire rate of spread (m/min)
   * \return Head fire rate of spread (m/min)
   */
  [[nodiscard]] constexpr MathSize headRos() const
  {
    return head_ros_;
  }
  /**
   * \brief Head fire spread direction
   * \return Head fire spread direction
   */
  [[nodiscard]] constexpr tbd::wx::Direction headDirection() const
  {
    return raz_;
  }
  /**
   * \brief Slope factor calculated from percent slope
   * \return Slope factor calculated from percent slope
   */
  [[nodiscard]] constexpr MathSize slopeFactor() const
  {
    // HACK: slope can be infinite, but anything > 60 is the same as 60
    // we already capped the percent slope when making the Cells
    return SlopeTable.at(percentSlope());
  }
  /**
   * \brief Calculate foliar moisture
   * \return Calculated foliar moisture
   */
  [[nodiscard]] constexpr MathSize foliarMoisture() const
  {
    // don't need to check  `&& nd_ < 50` in second part because of reordering
    return nd_ >= 50
           ? 120.0
         : nd_ >= 30
           ? 32.9 + 3.17 * nd_ - 0.0288 * nd_ * nd_
           : 85.0 + 0.0189 * nd_ * nd_;
  }
  /**
   * \brief Whether or not there is no spread for given conditions
   * \return Whether or not there is no spread for given conditions
   */
  [[nodiscard]] constexpr bool isInvalid() const
  {
    return -1 == head_ros_;
  }
  // required for making a map of SpreadInfo objects
  constexpr SpreadInfo() noexcept
    : offsets_({}),
      max_intensity_(INVALID_INTENSITY),
      key_(0),
      weather_(nullptr),
      time_(-1),
      l_b_(-1),
      head_ros_(INVALID_ROS),
      cfb_(-1),
      cfc_(-1),
      tfc_(-1),
      sfc_(-1),
      is_crown_(false),
      raz_(tbd::wx::Direction::Invalid),
      nd_(-1) {
      };
  SpreadInfo(
    const int year,
    const int month,
    const int day,
    const int hour,
    const int minute,
    const MathSize latitude,
    const MathSize longitude,
    const ElevationSize elevation,
    const SlopeSize slope,
    const AspectSize aspect,
    const char* fuel_name,
    const wx::FwiWeather* weather);
  SpreadInfo(
    const tm& start_date,
    const MathSize latitude,
    const MathSize longitude,
    const ElevationSize elevation,
    const SlopeSize slope,
    const AspectSize aspect,
    const char* fuel_name,
    const wx::FwiWeather* weather);
  MathSize crownFractionBurned() const
  {
    return cfb_;
  }
  MathSize crownFuelConsumption() const
  {
    return cfc_;
  }
  char fireDescription() const
  {
    return cfb_ >= 0.9 ? 'C' : (cfb_ < 0.1 ? 'S' : 'I');
  }
  MathSize surfaceFuelConsumption() const
  {
    return sfc_;
  }
  MathSize totalFuelConsumption() const
  {
    return tfc_;
  }
private:
  /**
   * Actual fire spread calculation without needing to worry about settings or scenarios
   */
  SpreadInfo(DurationSize time,
             MathSize min_ros,
             MathSize cell_size,
             const SlopeSize slope,
             const AspectSize aspect,
             const char* fuel_name,
             int nd,
             const wx::FwiWeather* weather);
  SpreadInfo(DurationSize time,
             MathSize min_ros,
             MathSize cell_size,
             const topo::SpreadKey& key,
             int nd,
             const wx::FwiWeather* weather);
  SpreadInfo(DurationSize time,
             MathSize min_ros,
             MathSize cell_size,
             const topo::SpreadKey& key,
             int nd,
             const wx::FwiWeather* weather,
             const wx::FwiWeather* weather_daily);
  /**
   * Do initial spread calculations
   * \return Initial head ros calculation (-1 for none)
   */
  static MathSize initial(SpreadInfo& spread,
                          const wx::FwiWeather& weather,
                          MathSize& ffmc_effect,
                          MathSize& wsv,
                          MathSize& rsoi,
                          const fuel::FuelType* const fuel,
                          bool has_no_slope,
                          MathSize heading_sin,
                          MathSize heading_cos,
                          MathSize bui_eff,
                          MathSize min_ros,
                          MathSize critical_surface_intensity);
  /**
   * \brief Offsets from origin point that represent spread under these conditions
   */
  OffsetSet offsets_{};
  /**
   * \brief Maximum intensity in any direction for spread (kW/m)
   */
  MathSize max_intensity_;
  /**
   * \brief Attributes for Cell spread is occurring in
   */
  topo::SpreadKey key_;
  /**
   * \brief FwiWeather determining spread
   */
  wx::FwiWeather const* weather_;
  /**
   * \brief Time that spread is occurring
   */
  DurationSize time_;
  MathSize l_b_;
  /**
   * \brief Head fire rate of spread (m/min)
   */
  MathSize head_ros_;
  MathSize cfb_;
  MathSize cfc_;
  MathSize tfc_;
  MathSize sfc_;
  bool is_crown_;
  /**
   * \brief Head fire spread direction
   */
  tbd::wx::Direction raz_;
  /**
   * \brief Difference between date and the date of minimum foliar moisture content (from ST-X-3)
   */
  int nd_;
};
}
