(function () {
  "use strict";

  function visible(node) {
    if (!node || !node.isConnected || node.getClientRects().length === 0) return false;
    var style = window.getComputedStyle(node);
    return style.visibility !== "hidden" && style.display !== "none";
  }

  function bounded(value, limit) {
    return String(value == null ? "" : value).replace(/\s+/g, " ").trim().slice(0, limit);
  }

  function barValue(bars, index) {
    if (!bars || index < 0) return null;
    var value = bars.valueAt(index);
    if (!value || value.length < 5) return null;
    return {
      time: value[0], open: value[1], high: value[2], low: value[3], close: value[4]
    };
  }

  function studyValue(data, index) {
    if (!data || index < 0) return null;
    var value = data.valueAt(index);
    if (!value || !Array.isArray(value)) return null;
    return value.slice(0, 24);
  }

  function accountMarkers() {
    var seen = {}, out = [];
    try {
      if (window.user && typeof window.user.username === "string") {
        var globalUsername = bounded(window.user.username, 80);
        if (globalUsername) {
          seen["global|" + globalUsername] = true;
          out.push({href: "", username: globalUsername, aria_label: "", title: "", text: ""});
        }
      }
    } catch (_) {}
    var selectors = [
      "a[href*='/u/']",
      "[data-username]",
      "[data-name='header-user-menu-button']",
      "button[aria-label*='user' i]",
      "button[title*='user' i]"
    ];
    selectors.forEach(function (selector) {
      Array.from(document.querySelectorAll(selector)).filter(visible).slice(0, 12).forEach(function (node) {
        var href = bounded(node.getAttribute && node.getAttribute("href"), 180);
        var username = bounded(node.getAttribute && node.getAttribute("data-username"), 80);
        var aria = bounded(node.getAttribute && node.getAttribute("aria-label"), 120);
        var title = bounded(node.getAttribute && node.getAttribute("title"), 120);
        var text = bounded(node.innerText || node.textContent, 120);
        var key = [href, username, aria, title, text].join("|");
        if (key && !seen[key]) {
          seen[key] = true;
          out.push({href: href, username: username, aria_label: aria, title: title, text: text});
        }
      });
    });
    return out.slice(0, 24);
  }

  var result = {
    script_id: "tradingview_read_state",
    script_version: "1.0",
    page_ready: document.readyState === "complete",
    location_url: String(window.location.href),
    title: bounded(document.title, 240),
    observed_epoch_ms: Date.now(),
    account_markers: accountMarkers(),
    charts: [],
    alert_inventory_count: null
  };

  try {
    var alertRows = Array.from(document.querySelectorAll("[data-name='alert-item']")).filter(visible);
    if (alertRows.length) result.alert_inventory_count = alertRows.length;
  } catch (_) {}

  try {
    var api = window.TradingViewApi;
    var count = api.chartsCount();
    for (var i = 0; i < count; i++) {
      var chart = api.chart(i);
      var widget = chart._chartWidget ||
        (typeof chart.chartWidget === "function" ? chart.chartWidget() : chart.chartWidget);
      var model = widget.model();
      var series = model.mainSeries();
      var bars = series.bars();
      var last = bars.lastIndex();
      var info = series.symbolInfo && series.symbolInfo();
      var seriesSymbol = "";
      try {
        seriesSymbol = bounded(
          (info && (info.pro_name || info.full_name || info.name)) ||
          (series.symbol && series.symbol()),
          100
        );
      } catch (_) {}
      var quote = null;
      try {
        var lastValue = series.lastValueData && series.lastValueData(false);
        if (lastValue) {
          quote = {
            price: lastValue.price == null ? null : lastValue.price,
            bid: lastValue.bid == null ? null : lastValue.bid,
            ask: lastValue.ask == null ? null : lastValue.ask
          };
        }
      } catch (_) {}
      var chartType = null;
      try { chartType = chart.chartType(); } catch (_) {
        try { chartType = series.style(); } catch (_) {}
      }
      var studies = [];
      var sources = [];
      try { sources = model.model().dataSources(); } catch (_) {}
      sources.slice(0, 80).forEach(function (source) {
        try {
          if (!source.metaInfo) return;
          var meta = source.metaInfo();
          var data = source.data && source.data();
          var dataLast = data && data.lastIndex ? data.lastIndex() : -1;
          studies.push({
            description: bounded(meta.description || meta.shortDescription || meta.id, 160),
            short_description: bounded(meta.shortDescription, 120),
            plots: (meta.plots || []).slice(0, 20).map(function (plot) {
              return {id: bounded(plot.id, 80), type: bounded(plot.type, 40)};
            }),
            current: studyValue(data, dataLast),
            closed: studyValue(data, dataLast - 1),
            previous_closed: studyValue(data, dataLast - 2)
          });
        } catch (_) {}
      });
      result.charts.push({
        index: i,
        interval: String(series.interval()),
        symbol: seriesSymbol,
        chart_type: chartType,
        last_index: last,
        current_bar: barValue(bars, last),
        closed_bar: barValue(bars, last - 1),
        previous_closed_bar: barValue(bars, last - 2),
        recent_closed_bars: Array.from({length: 25}, function (_, offset) {
          return barValue(bars, last - 1 - offset);
        }).filter(function (bar) { return bar !== null; }),
        quote: quote,
        studies: studies
      });
    }
  } catch (error) {
    result.read_error = bounded(error && error.message ? error.message : error, 240);
  }
  return result;
})()
