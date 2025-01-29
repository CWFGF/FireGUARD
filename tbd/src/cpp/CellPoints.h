/* Copyright (c) Jordan Evens, 2005, 2021 */
/* Copyright (c) Queen's Printer for Ontario, 2020. */
/* Copyright (c) His Majesty the King in Right of Canada as represented by the Minister of Natural Resources, 2021-2024. */

/* SPDX-License-Identifier: AGPL-3.0-or-later */

#pragma once
#include "stdafx.h"
#include "InnerPos.h"
#include "IntensityMap.h"

namespace tbd::sim
{
using tbd::wx::Direction;
// using sim::CellPoints;
using topo::Cell;
using topo::SpreadKey;
class SpreadData : std::tuple<DurationSize, IntensitySize, ROSSize, Direction, Direction>
{
public:
  using std::tuple<DurationSize, IntensitySize, ROSSize, Direction, Direction>::tuple;
  DurationSize time() const
  {
    return std::get<0>(*this);
  }
  IntensitySize intensity() const
  {
    return std::get<1>(*this);
  }
  ROSSize ros() const
  {
    return std::get<2>(*this);
  }
  Direction direction() const
  {
    return std::get<3>(*this);
  }
  Direction direction_previous() const
  {
    return std::get<4>(*this);
  }
};

static constexpr size_t FURTHEST_N = 0;
static constexpr size_t FURTHEST_NNE = 1;
static constexpr size_t FURTHEST_NE = 2;
static constexpr size_t FURTHEST_ENE = 3;
static constexpr size_t FURTHEST_E = 4;
static constexpr size_t FURTHEST_ESE = 5;
static constexpr size_t FURTHEST_SE = 6;
static constexpr size_t FURTHEST_SSE = 7;
static constexpr size_t FURTHEST_S = 8;
static constexpr size_t FURTHEST_SSW = 9;
static constexpr size_t FURTHEST_SW = 10;
static constexpr size_t FURTHEST_WSW = 11;
static constexpr size_t FURTHEST_W = 12;
static constexpr size_t FURTHEST_WNW = 13;
static constexpr size_t FURTHEST_NW = 14;
static constexpr size_t FURTHEST_NNW = 15;
static constexpr size_t NUM_DIRECTIONS = 16;

static constexpr auto MASK_NE = DIRECTION_N & DIRECTION_NE & DIRECTION_E;
static constexpr auto MASK_SE = DIRECTION_S & DIRECTION_SE & DIRECTION_E;
static constexpr auto MASK_SW = DIRECTION_S & DIRECTION_SW & DIRECTION_W;
static constexpr auto MASK_NW = DIRECTION_N & DIRECTION_NW & DIRECTION_W;
// mask of sides that would need to be burned for direction to not matter
static constexpr std::array<CellIndex, NUM_DIRECTIONS> DIRECTION_MASKS{
  DIRECTION_N,
  MASK_NE,
  MASK_NE,
  MASK_NE,
  DIRECTION_E,
  MASK_SE,
  MASK_SE,
  MASK_SE,
  DIRECTION_S,
  MASK_SW,
  MASK_SW,
  MASK_SW,
  DIRECTION_W,
  MASK_NW,
  MASK_NW,
  MASK_NW};

class CellPointsMap;
// using dist_pt = pair<DistanceSize, InnerPos>;
// using array_cellpts = std::array<dist_pt, NUM_DIRECTIONS>;
using array_dists = std::array<DistanceSize, NUM_DIRECTIONS>;
using array_pts = std::array<InnerPos, NUM_DIRECTIONS>;
// using array_cellpts = pair<CellPoints::array_dists, CellPoints::array_pts>;
using array_dirs = std::array<MathSize, NUM_DIRECTIONS>;
using array_cellpts = std::tuple<array_dists, array_pts, array_dirs>;
//   using array_cellpts = std::array<DistanceSize, NUM_DIRECTIONS>;
class CellPointArrays
  : public array_cellpts
{
public:
  using array_cellpts::array_cellpts;
  inline const array_dists& distances() const
  {
    return std::get<0>(*this);
  }
  inline const array_pts& points() const
  {
    return std::get<1>(*this);
  }
  inline const array_dirs& directions() const
  {
    return std::get<2>(*this);
  }
  inline array_dists& distances()
  {
    return std::get<0>(*this);
  }
  inline array_pts& points()
  {
    return std::get<1>(*this);
  }
  inline array_dirs& directions()
  {
    return std::get<2>(*this);
  }
};
/**
 * Points in a cell furthest in each direction
 */
class CellPoints
{
public:
  using spreading_points = map<SpreadKey, vector<pair<Location, CellPoints>>>;
  CellPoints() noexcept;
  //   // HACK: so we can emplace with NULL
  //   CellPoints(size_t) noexcept;
  // HACK: so we can emplace with nullptr
  CellPoints(const CellPoints* rhs) noexcept;
  //   CellPoints(const vector<InnerPos>& pts) noexcept;
  CellPoints(
    const XYPos& src,
    const SpreadData& spread_current,
    const XYSize x,
    const XYSize y) noexcept;
  CellPoints(CellPoints&& rhs) noexcept = default;
  CellPoints(const CellPoints& rhs) noexcept = default;
  CellPoints& operator=(CellPoints&& rhs) noexcept = default;
  CellPoints& operator=(const CellPoints& rhs) noexcept = default;
  CellPoints& insert(
    const XYPos& src,
    const SpreadData& spread_current,
    const XYSize x,
    const XYSize y) noexcept;
  CellPoints& insert(const InnerPos& p) noexcept;
  //   template <class _ForwardIterator>
  //   CellPoints& insert(_ForwardIterator begin, _ForwardIterator end)
  //   {
  //     // don't do anything if empty
  //     if (end != begin)
  //     {
  //       auto it = begin;
  //       while (end != it)
  //       {
  //          (*it);
  //         ++it;
  //       }
  //     }
  //     return *this;
  //   }
  void add_source(const CellIndex src);
  CellIndex sources() const
  {
    return src_;
  }
  CellPoints& merge(const CellPoints& rhs);
  set<XYPos> unique() const noexcept;
#ifdef DEBUG_CELLPOINTS
  size_t size() const noexcept;
#endif
  bool operator<(const CellPoints& rhs) const noexcept;
  bool operator==(const CellPoints& rhs) const noexcept;
  [[nodiscard]] Location location() const noexcept;
  void clear();
  //   const array_pts points() const;
  bool empty() const;
  SpreadData spread_arrival_;
  SpreadData spread_internal_;
  SpreadData spread_exit_;
  // DurationSize arrival_time_;
  // IntensitySize intensity_at_arrival_;
  // ROSSize ros_at_arrival_;
  // Direction raz_at_arrival_;
  // friend CellPointsMap;
  // FIX: just access directly for now
public:
  CellPointArrays pts_;
  // use Idx instead of Location so it can be negative (invalid)
  CellPos cell_x_y_;
  CellIndex src_;
private:
  CellPoints(const Idx cell_x, const Idx cell_y) noexcept;
  CellPoints(const XYPos& p) noexcept;
};

using spreading_points = CellPoints::spreading_points;
class Scenario;
// map that merges items when try_emplace doesn't insert
class CellPointsMap
{
public:
  CellPointsMap();
  // CellPoints& insert(
  //   const DurationSize& arrival_time,
  //   const IntensitySize intensity,
  //   const ROSSize& ros,
  //   const Direction& raz,
  //   const XYSize x,
  //   const XYSize y) noexcept;
  CellPoints& insert(
    const XYPos& src,
    const SpreadData& spread_current,
    const XYSize x,
    const XYSize y) noexcept;
  CellPointsMap& merge(
    const BurnedData& unburnable,
    const CellPointsMap& rhs) noexcept;
  set<XYPos> unique() const noexcept;
#ifdef DEBUG_CELLPOINTS
  size_t size() const noexcept;
#endif
  // apply function to each CellPoints within and remove matches
  void remove_if(std::function<bool(const pair<Location, CellPoints>&)> F) noexcept;
  // FIX: public for debugging right now
  // private:
  map<Location, CellPoints> map_;
};
}
