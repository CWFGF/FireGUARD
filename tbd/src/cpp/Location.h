/* Copyright (c) Queen's Printer for Ontario, 2020. */
/* Copyright (c) His Majesty the King in Right of Canada as represented by the Minister of Natural Resources, 2021-2024. */

/* SPDX-License-Identifier: AGPL-3.0-or-later */

#pragma once
#include "stdafx.h"
#include "Util.h"
#include "Log.h"
namespace tbd::topo
{
// have static versions of these outside Position so we can test with static_assert
/**
 * \brief Create a hash from given values
 * \param XYBits Number of bits to use for storing one coordinate of Position data
 * \param row Row
 * \param column Column
 * \return Hash
 */
[[nodiscard]] static inline constexpr HashSize do_hash(
  const uint32_t XYBits,
  const Idx row,
  const Idx column) noexcept
{
  return (static_cast<HashSize>(row) << XYBits) + static_cast<HashSize>(column);
}
/**
 * \brief Row from hash
 * \param XYBits Number of bits to use for storing one coordinate of Position data
 * \param hash hash to extract row from
 * \return Row from hash
 */
[[nodiscard]] static inline constexpr Idx unhash_row(
  const uint32_t XYBits,
  const Topo hash) noexcept
{
  // don't need to use mask since bits just get shifted out
  return static_cast<Idx>(hash >> XYBits);
}
/**
 * \brief Column
 * \param ColumnMask Hash mask for bits being used for Position data
 * \param hash hash to extract column from
 * \return Column
 */
[[nodiscard]] static inline constexpr Idx unhash_column(
  const Topo ColumnMask,
  const Topo hash) noexcept
{
  return static_cast<Idx>(hash & ColumnMask);
}
/**
 * \brief A Position with a row and column.
 */
template <class V>
class Position
{
public:
  Position() = default;
  /**
   * \brief Row
   * \return Row
   */
  [[nodiscard]] constexpr Idx row() const noexcept
  {
    return unhashRow(hash());
  }
  /**
   * \brief Column
   * \return Column
   */
  [[nodiscard]] constexpr Idx column() const noexcept
  {
    return unhashColumn(hash());
  }
  /**
   * \brief Hash derived from row and column
   * \return Hash derived from row and column
   */
  [[nodiscard]] constexpr HashSize hash() const noexcept
  {
#ifdef DEBUG_POINTS
    constexpr int num_bits = std::numeric_limits<HashSize>::digits;
    constexpr Topo m = util::bit_mask<num_bits, Topo>();
    logging::check_equal(
      static_cast<HashSize>(topo_data_),
      static_cast<HashSize>(m & topo_data_),
      "hash()");
#endif
    // can get away with just casting because all the other bits are outside this area
    return static_cast<HashSize>(topo_data_);
  }
  /**
   * \brief Equality operator
   * \param rhs Position to compare to
   * \return Whether or not these are equivalent
   */
  [[nodiscard]] constexpr bool operator==(const Position& rhs) const noexcept
  {
    return hash() == rhs.hash();
  }
  /**
   * \brief Inequality operator
   * \param rhs Position to compare to
   * \return Whether or not these are not equivalent
   */
  [[nodiscard]] constexpr bool operator!=(const Position& rhs) const noexcept
  {
    return !(*this == rhs);
  }
protected:
  /**
   * \brief Stored hash that contains row and column data
   */
  V topo_data_;
  /**
   * \brief Number of bits to use for storing one coordinate of Position data
   */
  static constexpr uint32_t XYBits = std::bit_width<uint32_t>(MAX_ROWS - 1);
  static_assert(util::pow_int<XYBits, size_t>(2) == MAX_ROWS);
  static_assert(util::pow_int<XYBits, size_t>(2) == MAX_COLUMNS);
  /**
   * \brief Number of bits to use for storing Position data
   */
  static constexpr uint32_t PositionBits = XYBits * 2;
  /**
   * \brief Hash mask for bits being used for Position data
   */
  static constexpr Topo ColumnMask = util::bit_mask<XYBits, Topo>();
  /**
   * \brief Hash mask for bits being used for Position data
   */
  static constexpr Topo HashMask = util::bit_mask<PositionBits, Topo>();
  static_assert(HashMask >= static_cast<size_t>(MAX_COLUMNS) * MAX_ROWS - 1);
  static_assert(HashMask <= std::numeric_limits<HashSize>::max());
  /**
   * \brief Construct with given hash that may contain data from subclasses
   * \param topo Hash to store
   */
  explicit constexpr Position(const Topo& topo) noexcept
    : topo_data_(topo)
  {
  }
  /**
   * \brief Create a hash from given values
   * \param row Row
   * \param column Column
   * \return Hash
   */
  [[nodiscard]] static constexpr HashSize doHash(
    const Idx row,
    const Idx column) noexcept
  {
    return do_hash(XYBits, row, column);
// make sure hashing/unhashing works
#define ROW_MIN 0
#define ROW_MAX (MAX_ROWS - 1)
#define COL_MIN 0
#define COL_MAX (MAX_COLUMNS - 1)
    static_assert(ROW_MIN == unhash_row(XYBits, do_hash(XYBits, ROW_MIN, COL_MIN)));
    static_assert(COL_MIN == unhash_column(ColumnMask, do_hash(XYBits, ROW_MIN, COL_MIN)));
    static_assert(ROW_MIN == unhash_row(XYBits, do_hash(XYBits, ROW_MIN, COL_MAX)));
    static_assert(COL_MAX == unhash_column(ColumnMask, do_hash(XYBits, ROW_MIN, COL_MAX)));
    static_assert(ROW_MAX == unhash_row(XYBits, do_hash(XYBits, ROW_MAX, COL_MIN)));
    static_assert(COL_MIN == unhash_column(ColumnMask, do_hash(XYBits, ROW_MAX, COL_MIN)));
    static_assert(ROW_MAX == unhash_row(XYBits, do_hash(XYBits, ROW_MAX, COL_MAX)));
    static_assert(COL_MAX == unhash_column(ColumnMask, do_hash(XYBits, ROW_MAX, COL_MAX)));
#undef ROW_MIN
#undef ROW_MAX
#undef COL_MIN
#undef COL_MAX
  }
  /**
   * \brief Row from hash
   * \param hash hash to extract row from
   * \return Row from hash
   */
  [[nodiscard]] static constexpr Idx unhashRow(const Topo hash) noexcept
  {
    return unhash_row(XYBits, hash);
  }
  /**
   * \brief Column
   * \param hash hash to extract column from
   * \return Column
   */
  [[nodiscard]] static constexpr Idx unhashColumn(const Topo hash) noexcept
  {
    return unhash_column(ColumnMask, hash);
  }
};
template <class V>
inline bool operator<(const Position<V>& lhs, const Position<V>& rhs)
{
  return lhs.hash() < rhs.hash();
}
template <class V>
inline bool operator>(const Position<V>& lhs, const Position<V>& rhs)
{
  return rhs < lhs;
}
template <class V>
inline bool operator<=(const Position<V>& lhs, const Position<V>& rhs)
{
  return !(lhs > rhs);
}
template <class V>
inline bool operator>=(const Position<V>& lhs, const Position<V>& rhs)
{
  return !(lhs < rhs);
}

#ifdef DEBUG_DIRECTIONS
// FIX: seems like there must be something with enum type that would be better?
static const map<CellIndex, const char*> DIRECTION_NAMES{
  {DIRECTION_NONE, "NONE"},
  {DIRECTION_W, "W"},
  {DIRECTION_E, "E"},
  {DIRECTION_S, "S"},
  {DIRECTION_N, "N"},
  {DIRECTION_SW, "SW"},
  {DIRECTION_NE, "NE"},
  {DIRECTION_NW, "NW"},
  {DIRECTION_SE, "SE"}};
#endif

class Location
  : public Position<HashSize>
{
public:
  using Position::Position;
  /**
   * \brief Construct using hash of row and column
   * \param hash HashSize derived form row and column
   */
// NOTE: do this so that we don't get warnings about unused variables in release mode
#ifdef NDEBUG
  explicit constexpr Location(const Idx, const Idx, const HashSize hash) noexcept
#else
  explicit Location(const Idx row, const Idx column, const HashSize hash) noexcept
#endif
    : Location(hash & HashMask)
  {
#ifdef DEBUG_GRIDS
    logging::check_fatal(
      row < 0 || row >= MAX_ROWS,
      "Row %d is out of bounds (%d, %d)",
      row,
      0,
      MAX_ROWS);
    logging::check_fatal(
      column < 0 || column >= MAX_COLUMNS,
      "Column %d is out of bounds (%d, %d)",
      column,
      0,
      MAX_COLUMNS);
    logging::check_fatal(
      (row != unhashRow(topo_data_))
        || column != unhashColumn(topo_data_),
      "Hash is incorrect (%d, %d)",
      row,
      column);
#endif
  }
  /**
   * \brief Constructor
   * \param row Row
   * \param column Column
   */
#ifdef NDEBUG
  constexpr
#endif
    Location(const Idx row, const Idx column) noexcept
    : Location(row, column, doHash(row, column) & HashMask)
  {
#ifdef DEBUG_GRIDS
    logging::check_fatal(row >= MAX_ROWS || column >= MAX_COLUMNS, "Location out of bounds (%d, %d)", row, column);
#endif
  }
  Location(const Coordinates& coord)
    : Location(std::get<0>(coord), std::get<1>(coord))
  {
  }
  /**
   * \brief Construct with given hash that may contain data from subclasses
   * \param hash_size Hash to store
   */
  explicit constexpr Location(const HashSize& hash_size) noexcept
    : Position(static_cast<HashSize>(hash_size))
  {
  }
  /**
   * \brief Construct with given hash that may contain data from subclasses
   * \param hash_size Hash to store
   */
  template <class P>
  explicit constexpr Location(const Position<P>& position) noexcept
    : Position(static_cast<HashSize>(position.hash()))
  {
  }
};
/**
 * Determine the direction that a given cell is in from another cell. This is the
 * same convention as wind (i.e. the direction it is coming from, not the direction
 * it is going towards).
 * @param src The cell to find directions relative to
 * @param dst The cell to find the direction of
 * @return Direction that you would have to go in to get to dst from src
 */
CellIndex
  relativeIndex(const Location& src, const Location& dst) noexcept;
}
