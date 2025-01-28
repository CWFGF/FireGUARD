/* Copyright (c) Queen's Printer for Ontario, 2020. */

/* SPDX-License-Identifier: AGPL-3.0-or-later */

#pragma once
#include "stdafx.h"
#include "Cell.h"

namespace tbd
{
using tbd::wx::Direction;
using topo::Location;
template <class S, int XMin, int XMax, int YMin, int YMax>
class BoundedPoint
  : public pair<S, S>
{
protected:
  using class_type = BoundedPoint<S, XMin, XMax, YMin, YMax>;
  static constexpr auto INVALID_X = XMin - 1;
  static constexpr auto INVALID_Y = YMin - 1;
public:
  using pair<S, S>::pair;
  constexpr BoundedPoint() noexcept
    : BoundedPoint(XMin - 1, YMin - 1)
  {
  }
  /**
   * \brief Add offset to position and return result
   */
  template <class T, class O>
  [[nodiscard]] constexpr T add(const O& o) const noexcept
  {
    return static_cast<T>(class_type(this->first + o.first, this->second + o.second));
  }
};
/**
 * \brief Offset from a position
 */
class Offset
  : public BoundedPoint<DistanceSize, -1, 1, -1, 1>
{
public:
  /**
   * \brief Collection of Offsets
   */
  using BoundedPoint<DistanceSize, -1, 1, -1, 1>::BoundedPoint;
};
using ROSOffset = std::tuple<IntensitySize, ROSSize, Direction, Offset>;
using OffsetSet = vector<ROSOffset>;
}
namespace tbd::sim
{
/**
 * \brief The position within a Cell that a spreading point has.
 */
class InnerPos
  : public BoundedPoint<InnerSize, 0, 1, 0, 1>
{
  using BoundedPoint<InnerSize, 0, 1, 0, 1>::BoundedPoint;
};
/**
 * \brief The position within the Environment that a spreading point has.
 */
class XYPos
  : public BoundedPoint<XYSize, 0, MAX_COLUMNS, 0, MAX_ROWS>
{
public:
  using BoundedPoint<XYSize, 0, MAX_COLUMNS, 0, MAX_ROWS>::BoundedPoint;
  constexpr Location location() const
  {
    // HACK: Location is (row, column) and this is (x, y)
    return {static_cast<Idx>(second), static_cast<Idx>(first)};
  }
};
/**
 * \brief The position within the Environment that a spreading point has.
 */
class CellPos
  : public BoundedPoint<Idx, 0, MAX_COLUMNS, 0, MAX_ROWS>
{
public:
  using BoundedPoint<Idx, 0, MAX_COLUMNS, 0, MAX_ROWS>::BoundedPoint;
  constexpr Location location() const
  {
    // HACK: Location is (row, column) and this is (x, y)
    return {static_cast<Idx>(second), static_cast<Idx>(first)};
  }
};
}
