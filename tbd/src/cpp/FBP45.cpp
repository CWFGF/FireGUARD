/* Copyright (c) Queen's Printer for Ontario, 2020. */

/* SPDX-License-Identifier: AGPL-3.0-or-later */

#include "stdafx.h"
#include "FBP45.h"
using tbd::util::LookupTable;
namespace tbd::fuel::fbp
{
MathSize FuelD1::isfD1(const SpreadInfo& spread,
                       const MathSize ros_multiplier,
                       const MathSize isi) const noexcept
{
  return limitIsf(ros_multiplier,
                  spread.slopeFactor() * (ros_multiplier * a())
                    * pow(1.0 - exp(negB() * isi), c()));
}
/**
 * \brief Surface Fuel Consumption (SFC) (kg/m^2) [GLC-X-10 eq 9a/9b]
 * \param ffmc Fine Fuel Moisture Code
 * \return Surface Fuel Consumption (SFC) (kg/m^2) [GLC-X-10 eq 9a/9b]
 */
[[nodiscard]] static constexpr MathSize
  calculate_surface_fuel_consumption_c1(const MathSize ffmc) noexcept
{
  return max(0.0,
             0.75 + ((ffmc > 84) ? 0.75 : -0.75) * sqrt(1 - exp(-0.23 * (ffmc - 84))));
}
/**
 * \brief Surface Fuel Consumption (SFC) (kg/m^2) [GLC-X-10 eq 9a/9b]
 * \return Surface Fuel Consumption (SFC) (kg/m^2) [GLC-X-10 eq 9a/9b]
 */
static LookupTable<&calculate_surface_fuel_consumption_c1> SURFACE_FUEL_CONSUMPTION_C1{};
MathSize FuelC1::surfaceFuelConsumption(const SpreadInfo& spread) const noexcept
{
  return SURFACE_FUEL_CONSUMPTION_C1(spread.ffmc().asValue());
}
MathSize FuelC2::surfaceFuelConsumption(const SpreadInfo& spread) const noexcept
{
  return SURFACE_FUEL_CONSUMPTION_MIXED_OR_C2(spread.bui().asValue());
}
MathSize FuelC6::finalRos(const SpreadInfo& spread,
                          const MathSize isi,
                          const MathSize cfb,
                          const MathSize rss) const noexcept
{
  const auto rsc = crownRateOfSpread(isi, spread.foliarMoisture());
  // using max with 0 is the same as ensuring rsc > rss
  return rss + cfb * max(0.0, rsc - rss);
}
/**
 * \brief Forest Floor Consumption (FFC) (kg/m^2) [ST-X-3 eq 13]
 * \param ffmc Fine Fuel Moisture Code
 * \return Forest Floor Consumption (FFC) (kg/m^2) [ST-X-3 eq 13]
 */
[[nodiscard]] static constexpr MathSize
  calculate_surface_fuel_consumption_c7_ffmc(const MathSize ffmc) noexcept
{
  return (ffmc > 70)
         ? 2.0 * (1.0 - exp(-0.104 * (ffmc - 70.0)))
         : 0.0;
}
/**
 * \brief Forest Floor Consumption (FFC) (kg/m^2) [ST-X-3 eq 13]
 * \return Forest Floor Consumption (FFC) (kg/m^2) [ST-X-3 eq 13]
 */
static LookupTable<&calculate_surface_fuel_consumption_c7_ffmc>
  SURFACE_FUEL_CONSUMPTION_C7_FFMC{};
/**
 * \brief Woody Fuel Consumption (WFC) (kg/m^2) [ST-X-3 eq 14]
 * \return Woody Fuel Consumption (WFC) (kg/m^2) [ST-X-3 eq 14]
 */
[[nodiscard]] static MathSize
  calculate_surface_fuel_consumption_c7_bui(const MathSize bui) noexcept
{
  return 1.5 * (1.0 - exp(-0.0201 * bui));
}
/**
 * \brief Woody Fuel Consumption (WFC) (kg/m^2) [ST-X-3 eq 14]
 * \return Woody Fuel Consumption (WFC) (kg/m^2) [ST-X-3 eq 14]
 */
static LookupTable<&calculate_surface_fuel_consumption_c7_bui>
  SURFACE_FUEL_CONSUMPTION_C7_BUI{};
MathSize FuelC7::surfaceFuelConsumption(const SpreadInfo& spread) const noexcept
{
  return SURFACE_FUEL_CONSUMPTION_C7_FFMC(spread.ffmc().asValue()) + SURFACE_FUEL_CONSUMPTION_C7_BUI(spread.bui().asValue());
}
[[nodiscard]] static constexpr MathSize
  calculate_surface_fuel_consumption_d2(const MathSize bui) noexcept
{
  return bui >= 80 ? 1.5 * (1.0 - exp(-0.0183 * bui)) : 0.0;
}
static LookupTable<&calculate_surface_fuel_consumption_d2> SURFACE_FUEL_CONSUMPTION_D2{};
MathSize FuelD2::surfaceFuelConsumption(const SpreadInfo& spread) const noexcept
{
  return SURFACE_FUEL_CONSUMPTION_D2(spread.bui().asValue());
}
MathSize FuelD2::calculateRos(const int,
                              const wx::FwiWeather& wx,
                              const MathSize isi) const noexcept
{
  return (wx.bui().asValue() >= 80) ? rosBasic(isi) : 0.0;
}
}
