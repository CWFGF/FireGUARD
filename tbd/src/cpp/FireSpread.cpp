/* Copyright (c) Queen's Printer for Ontario, 2020. */
/* Copyright (c) His Majesty the King in Right of Canada as represented by the Minister of Natural Resources, 2021-2024. */

/* SPDX-License-Identifier: AGPL-3.0-or-later */

#include "stdafx.h"
#include "FireSpread.h"
#include "FuelLookup.h"
#include "FuelType.h"
#include "Scenario.h"
#include "Settings.h"
#include "unstable.h"
#include "SpreadAlgorithm.h"

namespace tbd::sim
{
// number of degrees between spread directions
// if not defined then use variable step degrees
// #define STEP

/**
 * \brief Maximum slope that affects ISI - everything after this is the same factor
 */
static constexpr auto MAX_SLOPE_FOR_FACTOR = 69;

SlopeTableArray make_slope_table() noexcept
{
  // HACK: slope can be infinite, but anything > max is the same as max
  // ST-X-3 Eq. 39 - Calculate Spread Factor
  // GLC-X-10 39a/b increase to 70% limit
  SlopeTableArray result{};
  for (size_t i = 0; i <= MAX_SLOPE_FOR_FACTOR; ++i)
  {
    result.at(i) = exp(3.533 * pow(i / 100.0, 1.2));
  }
  constexpr auto MAX_SLOPE = MAX_SLOPE_FOR_FACTOR + 1;
  // anything >=70 is just 10
  std::fill(
    &(result[MAX_SLOPE]),
    &(result[MAX_SLOPE_FOR_DISTANCE]),
    10.0);
  static_assert(result.size() == MAX_SLOPE_FOR_DISTANCE + 1);
  return result;
}
const SlopeTableArray SpreadInfo::SlopeTable = make_slope_table();
int calculate_nd_ref_for_point(const int elevation, const topo::Point& point) noexcept
{
  // NOTE: cffdrs R package stores longitude West as a positive, so this would be `- long`
  const auto latn = elevation <= 0
                    ? (46.0 + 23.4 * exp(-0.0360 * (150 + point.longitude())))
                    : (43.0 + 33.7 * exp(-0.0351 * (150 + point.longitude())));
  // add 0.5 to round by truncating
  return static_cast<int>(truncl(
    0.5 + (elevation <= 0 ? 151.0 * (point.latitude() / latn) : 142.1 * (point.latitude() / latn) + 0.0172 * elevation)));
}
int calculate_nd_for_point(const Day day, const int elevation, const topo::Point& point)
{
  return static_cast<int>(abs(day - calculate_nd_ref_for_point(elevation, point)));
}
static MathSize calculate_standard_back_isi_wsv(const MathSize v) noexcept
{
  return 0.208 * exp(-0.05039 * v);
}
static const util::LookupTable<&calculate_standard_back_isi_wsv> STANDARD_BACK_ISI_WSV{};
static constexpr MathSize calculate_standard_wsv(const MathSize v) noexcept
{
  return v < 40.0
         ? exp(0.05039 * v)
         : 12.0 * (1.0 - exp(-0.0818 * (v - 28)));
}
static const util::LookupTable<&calculate_standard_wsv> STANDARD_WSV{};
SpreadInfo::SpreadInfo(const Scenario& scenario,
                       const DurationSize time,
                       const topo::SpreadKey& key,
                       const int nd,
                       const wx::FwiWeather* weather)
  : SpreadInfo(scenario, time, key, nd, weather, scenario.weather_daily(time))
{
}
MathSize SpreadInfo::initial(SpreadInfo& spread,
                             const wx::FwiWeather& weather,
                             MathSize& ffmc_effect,
                             MathSize& wsv,
                             MathSize& rso,
                             const fuel::FuelType* const fuel,
                             bool has_no_slope,
                             MathSize heading_sin,
                             MathSize heading_cos,
                             MathSize bui_eff,
                             MathSize min_ros,
                             MathSize critical_surface_intensity)
{
  ffmc_effect = spread.ffmcEffect();
  // needs to be non-const so that we can update if slopeEffect changes direction
  MathSize raz = spread.wind().heading();
  const auto isz = 0.208 * ffmc_effect;
  wsv = spread.wind().speed().asValue();
  if (!has_no_slope)
  {
    const auto isf1 = fuel->calculateIsf(spread, isz);
    // const auto isf = (0.0 == isf1) ? isz : isf1;
    // we know const auto isz = 0.208 * ffmc_effect;
    auto wse = 0.0 == isf1 ? 0 : log(isf1 / isz) / 0.05039;
    if (wse > 40)
    {
      wse = 28.0 - log(1.0 - min(0.999 * 2.496 * ffmc_effect, isf1) / (2.496 * ffmc_effect)) / 0.0818;
    }
    // we know that at->raz is already set to be the wind heading
    const auto wsv_x = spread.wind().wsvX() + wse * heading_sin;
    const auto wsv_y = spread.wind().wsvY() + wse * heading_cos;
    wsv = sqrt(wsv_x * wsv_x + wsv_y * wsv_y);
    raz = (0 == wsv) ? 0 : acos(wsv_y / wsv);
    if (wsv_x < 0)
    {
      raz = util::RAD_360 - raz;
    }
  }
  spread.raz_ = tbd::wx::Direction(raz, true);
  const auto isi = isz * STANDARD_WSV(wsv);
  // FIX: make this a member function so we don't need to preface head_ros_
  spread.head_ros_ = fuel->calculateRos(spread.nd(),
                                        weather,
                                        isi)
                   * bui_eff;
  if (min_ros > spread.head_ros_)
  {
    spread.head_ros_ = INVALID_ROS;
  }
  else
  {
    spread.sfc_ = fuel->surfaceFuelConsumption(spread);
    rso = fuel::FuelType::criticalRos(spread.sfc_, critical_surface_intensity);
    const auto sfi = fuel::fire_intensity(spread.sfc_, spread.head_ros_);
    spread.is_crown_ = fuel::FuelType::isCrown(critical_surface_intensity,
                                               sfi);
    if (spread.is_crown_)
    {
      spread.head_ros_ = fuel->finalRos(spread,
                                        isi,
                                        fuel->crownFractionBurned(spread.head_ros_, rso),
                                        spread.head_ros_);
    }
  }
  return spread.head_ros_;
}
static MathSize find_min_ros(const Scenario& scenario, const DurationSize time)
{
  return Settings::deterministic()
         ? Settings::minimumRos()
         : std::max(scenario.spreadThresholdByRos(time),
                    Settings::minimumRos());
}
SpreadInfo::SpreadInfo(const Scenario& scenario,
                       const DurationSize time,
                       const topo::SpreadKey& key,
                       const int nd,
                       const wx::FwiWeather* weather,
                       const wx::FwiWeather* weather_daily)
  : SpreadInfo(time,
               find_min_ros(scenario, time),
               scenario.cellSize(),
               key,
               nd,
               weather,
               weather_daily)
{
}
static topo::SpreadKey make_key(const SlopeSize slope,
                                const AspectSize aspect,
                                const char* fuel_name)
{
  const auto lookup = tbd::sim::Settings::fuelLookup();
  const auto key = topo::Cell::key(topo::Cell::hashCell(slope,
                                                        aspect,
                                                        fuel::FuelType::safeCode(lookup.byName(fuel_name))));
  const auto a = topo::Cell::aspect(key);
  const auto s = topo::Cell::slope(key);
  const auto fuel = fuel::fuel_by_code(topo::Cell::fuelCode(key));
  logging::check_equal(s, slope, "slope");
  logging::check_equal(a, (0 == slope ? 0 : aspect), "aspect");
  logging::check_equal(fuel->name(), fuel_name, "fuel");
  return key;
}
SpreadInfo::SpreadInfo(
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
  const wx::FwiWeather* weather)
  : SpreadInfo(util::to_tm(year, month, day, hour, minute),
               latitude,
               longitude,
               elevation,
               slope,
               aspect,
               fuel_name,
               weather)
{
}
SpreadInfo::SpreadInfo(
  const tm& start_date,
  const MathSize latitude,
  const MathSize longitude,
  const ElevationSize elevation,
  const SlopeSize slope,
  const AspectSize aspect,
  const char* fuel_name,
  const wx::FwiWeather* weather)
  : SpreadInfo(util::to_time(start_date),
               0.0,
               100.0,
               slope,
               aspect,
               fuel_name,
               calculate_nd_for_point(start_date.tm_yday, elevation, tbd::topo::Point(latitude, longitude)),
               weather)
{
}
SpreadInfo::SpreadInfo(const DurationSize time,
                       const MathSize min_ros,
                       const MathSize cell_size,
                       const SlopeSize slope,
                       const AspectSize aspect,
                       const char* fuel_name,
                       const int nd,
                       const wx::FwiWeather* weather)
  : SpreadInfo(time, min_ros, cell_size, make_key(slope, aspect, fuel_name), nd, weather, weather)
{
}
SpreadInfo::SpreadInfo(const DurationSize time,
                       const MathSize min_ros,
                       const MathSize cell_size,
                       const topo::SpreadKey& key,
                       const int nd,
                       const wx::FwiWeather* weather)
  : SpreadInfo(time, min_ros, cell_size, key, nd, weather, weather)
{
}
SpreadInfo::SpreadInfo(const DurationSize time,
                       const MathSize min_ros,
                       const MathSize cell_size,
                       const topo::SpreadKey& key,
                       const int nd,
                       const wx::FwiWeather* weather,
                       const wx::FwiWeather* weather_daily)
  : offsets_({}),
    max_intensity_(INVALID_INTENSITY),
    key_(key),
    weather_(weather),
    time_(time),
    head_ros_(INVALID_ROS),
    cfb_(-1),
    cfc_(-1),
    tfc_(-1),
    sfc_(-1),
    is_crown_(false),
    raz_(tbd::wx::Direction::Invalid),
    nd_(nd)
{
  // HACK: use weather_daily to figure out probability of spread but hourly for ROS
  const auto slope_azimuth = topo::Cell::aspect(key_);
  const auto fuel = fuel::fuel_by_code(topo::Cell::fuelCode(key_));
  const auto has_no_slope = 0 == percentSlope();
  MathSize heading_sin = 0;
  MathSize heading_cos = 0;
  if (!has_no_slope)
  {
    const auto heading = util::to_heading(
      util::to_radians(static_cast<MathSize>(slope_azimuth)));
    heading_sin = _sin(heading);
    heading_cos = _cos(heading);
  }
  // HACK: only use BUI from hourly weather for both calculations
  const auto _bui = bui().asValue();
  const auto bui_eff = fuel->buiEffect(_bui);
  // FIX: gets calculated when not necessary sometimes
  const auto critical_surface_intensity = fuel->criticalSurfaceIntensity(*this);
  MathSize ffmc_effect;
  MathSize wsv;
  MathSize rso;
  if (min_ros > SpreadInfo::initial(
        *this,
        *weather_daily,
        ffmc_effect,
        wsv,
        rso,
        fuel,
        has_no_slope,
        heading_sin,
        heading_cos,
        bui_eff,
        min_ros,
        critical_surface_intensity)
      || sfc_ < COMPARE_LIMIT)
  {
    return;
  }
  // Now use hourly weather for actual spread calculations
  // don't check again if pointing at same weather
  if (weather != weather_daily)
  {
    if ((min_ros > SpreadInfo::initial(*this,
                                       *weather,
                                       ffmc_effect,
                                       wsv,
                                       rso,
                                       fuel,
                                       has_no_slope,
                                       heading_sin,
                                       heading_cos,
                                       bui_eff,
                                       min_ros,
                                       critical_surface_intensity)
         || sfc_ < COMPARE_LIMIT))
    {
      // no spread with hourly weather
      // NOTE: only would happen if FFMC hourly is lower than FFMC daily?
      return;
    }
  }
  logging::verbose("initial ros is %f", head_ros_);
  const auto back_isi = ffmc_effect * STANDARD_BACK_ISI_WSV(wsv);
  auto back_ros = fuel->calculateRos(nd,
                                     *weather,
                                     back_isi)
                * bui_eff;
  if (is_crown_)
  {
    back_ros = fuel->finalRos(*this,
                              back_isi,
                              fuel->crownFractionBurned(back_ros, rso),
                              back_ros);
  }
  tfc_ = sfc_;
  // don't need to re-evaluate if crown with new head_ros_ because it would only go up if is_crown_
  if (fuel->canCrown() && is_crown_)
  {
    // wouldn't be crowning if ros is 0 so that's why this is in an else
    cfb_ = fuel->crownFractionBurned(head_ros_, rso);
    cfc_ = fuel->crownConsumption(cfb_);
    tfc_ += cfc_;
  }
  // max intensity should always be at the head
  max_intensity_ = fuel::fire_intensity(tfc_, head_ros_);
  l_b_ = fuel->lengthToBreadth(wsv);
  const HorizontalAdjustment correction_factor = horizontal_adjustment(slope_azimuth, percentSlope());
  // const auto spread_algorithm = OriginalSpreadAlgorithm(1.0, cell_size, min_ros);
  const auto spread_algorithm = WidestEllipseAlgorithm(MAX_SPREAD_ANGLE, cell_size, min_ros);
  offsets_ = spread_algorithm.calculate_offsets(correction_factor,
                                                tfc_,
                                                raz_.asRadians(),
                                                head_ros_,
                                                back_ros,
                                                l_b_);
  // might not be correct depending on slope angle correction
  // #ifdef DEBUG_POINTS
  //   // if (head_ros_ >= min_ros)
  //   {
  //     logging::check_fatal(
  //       offsets_.empty(),
  //       "Empty when ros of %f >= %f",
  //       head_ros_,
  //       min_ros);
  //   }
  // #endif
  // if no offsets then not spreading so invalidate head_ros_
  if (0 == offsets_.size())
  {
    head_ros_ = INVALID_ROS;
    max_intensity_ = INVALID_INTENSITY;
    cfb_ = -1;
    cfc_ = -1;
    tfc_ = -1;
    sfc_ = -1;
    is_crown_ = false;
    raz_ = tbd::wx::Direction::Invalid;
  }
}
// MathSize SpreadInfo::calculateSpreadProbability(const MathSize ros)
// {
//   // note: based off spread event probability from wotton
//   return 1 / (1 + exp(1.64 - 0.16 * ros));
// }
}
