"""Screen situations real devices produce, on dumps of a made-up shopping app ("Pantry", 1080x2400).

Each fixture recreates one situation seen on a real phone: screen-reader-only prices, a button drawn under
another one, a card under the tab bar, a non-fullscreen permission dialog, a Chrome custom tab.
"""

import argparse
import random

import pytest

from mobiletester.android import cli, hierarchy
from mobiletester.core import guard

DISPLAY = (1080, 2400)
MILK = "Pantry Semi-skimmed Milk 2 L"


def _snap(fixture_xml, name):
    return hierarchy.parse(fixture_xml(name), display=DISPLAY)


def test_screen_reader_only_text_is_kept(fixture_xml):
    # Prices are rendered as 6x8 px TextViews for TalkBack; the visible digits are drawn separately.
    snap = _snap(fixture_xml, "pantry_search_results.xml")
    price = hierarchy.find_by_text(snap, "Price: $1.99")
    assert price, "price text must be listed"
    assert price[0].sr_only and "sr-only" in price[0].describe()
    assert hierarchy.find_by_text(snap, "$1.00 per liter")


def test_sliver_tap_targets_are_still_dropped(fixture_xml):
    snap = _snap(fixture_xml, "pantry_search_results.xml")
    assert all(e.bounds.width >= 12 and e.bounds.height >= 12 for e in snap.elements if e.interactive)
    assert not hierarchy.find_by_text(snap, "Pantry Whole Milk 1 L")


def test_screen_size_comes_from_display_not_dialog_window(fixture_xml):
    snap = _snap(fixture_xml, "pantry_permission_dialog.xml")
    assert (snap.screen.right, snap.screen.bottom) == DISPLAY
    # Without a display size the dialog window bounds are the best guess.
    fallback = hierarchy.parse(fixture_xml("pantry_permission_dialog.xml"))
    assert (fallback.screen.right, fallback.screen.bottom) != DISPLAY


def test_element_at_picks_topmost_not_smallest(fixture_xml):
    # The "add to list" button (113x113) lies under the quantity field; the tap reaches the field.
    snap = _snap(fixture_xml, "pantry_stepper.xml")
    hit = hierarchy.element_at(snap, 848, 671)
    assert hit is not None and hit.editable and hit.label == "1"


def test_tap_point_avoids_bottom_navigation(fixture_xml):
    snap = _snap(fixture_xml, "pantry_recipes.xml")
    card = hierarchy.find_by_text(snap, "Tray bake with pumpkin and sprouts")[0]
    nav_top = min(e.bounds.top for e in snap.elements if e.label == "Home")
    assert card.bounds.center[1] > nav_top, "fixture premise: the card's center is under the tab bar"
    point = hierarchy.visible_point(snap, card)
    assert point is not None
    x, y = point
    assert card.bounds.contains(x, y) and y < nav_top
    assert hierarchy.element_at(snap, x, y) is card
    assert hierarchy.find_by_text(snap, "Recipes")  # sanity: tab bar is in the dump


def test_keyboard_area_counts_as_covering(fixture_xml):
    # A keyboard window as Gboard reports it on a 1080x2400 phone: [0,1517][1080,2400].
    snap = _snap(fixture_xml, "pantry_search_results.xml")
    keyboard = hierarchy.Bounds(0, 1517, 1080, 2400)
    under = [e for e in snap.elements if e.clickable and e.bounds.top >= keyboard.top]
    assert under, "fixture premise: some controls sit where the keyboard would be"
    assert all(hierarchy.visible_point(snap, e, (keyboard,)) is None for e in under)
    above = next(e for e in snap.elements if e.editable)
    x, y = hierarchy.human_point(snap, above, random.Random(1), (keyboard,))
    assert not keyboard.contains(x, y)


def test_fully_covered_element_has_no_tap_point(fixture_xml):
    snap = _snap(fixture_xml, "pantry_stepper.xml")
    add_to_list = hierarchy.find_by_text(snap, f"Add to list {MILK}")[0]
    assert hierarchy.visible_point(snap, add_to_list) is None


def test_web_content_is_marked(fixture_xml):
    snap = _snap(fixture_xml, "pantry_web_home_with_card.xml")
    assert hierarchy.find_by_text(snap, "Close")[0].web
    assert not next(e for e in snap.elements if e.cls == "WebView").web
    assert not any(e.web for e in _snap(fixture_xml, "pantry_home_with_card.xml").elements)


def test_web_overlay_first_in_page_is_not_treated_as_covered(fixture_xml):
    # Inside a WebView the page decides what is on top (CSS position and z-index), not the order of the dump:
    # the notice comes first in the page but is drawn over the scroll area and the tab bar.
    snap = _snap(fixture_xml, "pantry_web_home_with_card.xml")
    close = hierarchy.find_by_text(snap, "Close")[0]
    assert hierarchy.visible_point(snap, close) is None, "fixture premise: dump order says the scroll area is on top"
    x, y = hierarchy.visible_point(snap, close, trust_web_order=False)
    assert close.bounds.contains(x, y)


def test_web_overlay_prefers_the_part_nothing_overlaps(fixture_xml):
    snap = _snap(fixture_xml, "pantry_web_home_with_card.xml")
    read_more = hierarchy.find_by_text(snap, "Read more")[0]
    x, y = hierarchy.visible_point(snap, read_more, trust_web_order=False)
    tab_top = hierarchy.find_by_text(snap, "Products")[0].bounds.top
    assert read_more.bounds.contains(x, y) and y < tab_top


def test_native_order_is_still_trusted(fixture_xml):
    snap = _snap(fixture_xml, "pantry_stepper.xml")
    add_to_list = hierarchy.find_by_text(snap, f"Add to list {MILK}")[0]
    assert hierarchy.visible_point(snap, add_to_list, trust_web_order=False) is None


def test_point_under_two_web_controls_names_both(fixture_xml):
    # A tap on the notice's button, where the tab bar lies behind it on screen but after it in the page.
    snap = _snap(fixture_xml, "pantry_web_home_with_card.xml")
    top = hierarchy.element_at(snap, 305, 2205)
    others = hierarchy.unsure_hits(snap, 305, 2205)
    assert {top.label, *(e.label for e in others)} == {"Products", "Read more"}
    assert not any(e.scrollable for e in others), "page scroll areas are background, not candidates"
    assert hierarchy.unsure_hits(_snap(fixture_xml, "pantry_stepper.xml"), 848, 671) == []


def test_tap_on_web_overlay_goes_ahead_with_a_note(fixture_xml, capsys):
    snap = _snap(fixture_xml, "pantry_web_home_with_card.xml")
    close = hierarchy.find_by_text(snap, "Close")[0]
    x, y = cli._tap_point(snap, close, argparse.Namespace(fast=False))
    assert close.bounds.contains(x, y)
    assert "web content" in capsys.readouterr().out


def test_tap_on_natively_covered_element_is_still_refused(fixture_xml):
    snap = _snap(fixture_xml, "pantry_stepper.xml")
    add_to_list = hierarchy.find_by_text(snap, f"Add to list {MILK}")[0]
    with pytest.raises(cli.NotFound, match="covered"):
        cli._tap_point(snap, add_to_list, argparse.Namespace(fast=True))


def test_coordinate_tap_label_names_every_candidate(fixture_xml):
    snap = _snap(fixture_xml, "pantry_web_home_with_card.xml")
    label = cli._hit_label(snap, 305, 2205)
    assert '"Products"' in label and '"Read more"' in label
    assert cli._hit_label(snap, 540, 330).endswith('"What are you looking for?" [click]')


def test_text_match_prefers_own_label_of_clickable(fixture_xml):
    snap = _snap(fixture_xml, "pantry_custom_tab.xml")
    matches = hierarchy.find_by_text(snap, "Close tab")
    assert [m.short_id for m in matches] == ["close_button"]


def test_text_match_prefers_label_starting_with_query(fixture_xml):
    snap = _snap(fixture_xml, "pantry_search_with_basket.xml")
    matches = hierarchy.find_by_text(snap, "Basket")
    assert [m.label for m in matches] == ["Basket 1 product"]


def test_permission_question_is_not_a_risky_action(fixture_xml):
    snap = _snap(fixture_xml, "pantry_permission_dialog.xml")
    assert not [e.describe() for e in snap.elements if e.risk]


def test_action_like():
    assert guard.action_like("Send feedback about time")
    assert guard.action_like("Buy now")
    assert not guard.action_like("Allow Pantry to send you notifications?")
    assert not guard.action_like("Share your favourite recipes with friends and family this weekend")
