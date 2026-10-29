package com.sqx.mt5bridge;

import javax.swing.*;
import javax.swing.event.ListSelectionEvent;
import javax.swing.event.ListSelectionListener;
import java.awt.*;
import java.io.BufferedReader;
import java.io.InputStreamReader;
import java.net.URI;
import java.net.http.HttpClient;
import java.net.http.HttpRequest;
import java.net.http.HttpResponse;
import java.util.regex.Matcher;
import java.util.regex.Pattern;

/**
 * SQX plugin tab – MT5BacktestBridge.
 *
 * When a strategy is selected, the plugin calls the bridge service
 * /backtest-settings endpoint and auto-populates Symbol, Period,
 * Date Range, and Initial Capital from the strategy's actual config XML.
 *
 * The endpoint extracts these values from the SQX internal API:
 *   - Symbol  → <Chart symbol="...">
 *   - Period  → <Chart timeframe="...">
 *   - Date range → <Setup dateFrom="..." dateTo="...">
 *   - Capital → <InitialCapital>
 */
public class UI extends JFrame {
    private static final String BRIDGE_URL = "http://localhost:8090";

    private final HttpClient client = HttpClient.newHttpClient();

    // ── UI components ─────────────────────────────────────────────────

    private JComboBox<String> projectCombo;
    private JComboBox<String> databankCombo;
    private JComboBox<String> strategyCombo;
    private JComboBox<String> symbolCombo;
    private JComboBox<String> periodCombo;
    private JTextField dateFromField;
    private JTextField dateToField;
    private JTextField initialCapitalField;

    // ── Known MT5 timeframes ──────────────────────────────────────────

    private static final String[] PERIODS = {
            "M1", "M5", "M15", "M30",
            "H1", "H4", "D1", "W1", "MN1"
    };

    // ── Constructor ────────────────────────────────────────────────────

    public UI() {
        super("SQX-MT5 Backtest Bridge");
        setDefaultCloseOperation(JFrame.EXIT_ON_CLOSE);
        setSize(750, 600);
        setLocationRelativeTo(null);
        initUI();
    }

    // ── UI Setup ───────────────────────────────────────────────────────

    private void initUI() {
        JPanel mainPanel = new JPanel(new BorderLayout(8, 8));
        mainPanel.setBorder(BorderFactory.createEmptyBorder(10, 10, 10, 10));

        // ── Section 1: STRATEGY ────────────────────────────────────────
        JPanel strategyPanel = new JPanel(new GridLayout(3, 2, 8, 6));
        strategyPanel.setBorder(BorderFactory.createTitledBorder("1. STRATEGY"));

        strategyPanel.add(new JLabel("Project:"));
        projectCombo = new JComboBox<>(new String[]{"Preliminary Tests"});
        strategyPanel.add(projectCombo);

        strategyPanel.add(new JLabel("Databank:"));
        databankCombo = new JComboBox<>(new String[]{"Results (13)"});
        strategyPanel.add(databankCombo);

        strategyPanel.add(new JLabel("Saved strategy:"));
        strategyCombo = new JComboBox<>();
        strategyCombo.addActionListener(e -> onStrategySelected());
        strategyPanel.add(strategyCombo);

        // ── Section 2: MT5 TEST CONFIGURATION ─────────────────────────
        JPanel mt5Panel = new JPanel(new GridLayout(8, 2, 8, 6));
        mt5Panel.setBorder(BorderFactory.createTitledBorder("2. MT5 TEST CONFIGURATION"));

        mt5Panel.add(new JLabel("Symbol:"));
        symbolCombo = new JComboBox<>();
        symbolCombo.setEditable(true);
        mt5Panel.add(symbolCombo);

        mt5Panel.add(new JLabel("Period:"));
        periodCombo = new JComboBox<>(PERIODS);
        mt5Panel.add(periodCombo);

        mt5Panel.add(new JLabel("Date range (as in SQX):"));
        JPanel datePanel = new JPanel(new FlowLayout(FlowLayout.LEFT, 4, 0));
        dateFromField = new JTextField(10);
        dateToField = new JTextField(10);
        datePanel.add(dateFromField);
        datePanel.add(new JLabel("→"));
        datePanel.add(dateToField);
        mt5Panel.add(datePanel);

        mt5Panel.add(new JLabel("Initial deposit (as in SQX):"));
        initialCapitalField = new JTextField("10000", 10);
        mt5Panel.add(initialCapitalField);

        // ── Buttons ────────────────────────────────────────────────────
        JPanel buttonPanel = new JPanel(new FlowLayout(FlowLayout.LEFT));
        JButton runBtn = new JButton("Run in MT5");
        JButton runAllBtn = new JButton("Run all strategies");
        runBtn.addActionListener(e -> runBacktest(false));
        runAllBtn.addActionListener(e -> runBacktest(true));
        buttonPanel.add(runBtn);
        buttonPanel.add(runAllBtn);

        // ── Assemble ───────────────────────────────────────────────────
        mainPanel.add(strategyPanel, BorderLayout.NORTH);
        mainPanel.add(mt5Panel, BorderLayout.CENTER);
        mainPanel.add(buttonPanel, BorderLayout.SOUTH);

        setContentPane(mainPanel);

        // ── Health check on startup ────────────────────────────────────
        SwingUtilities.invokeLater(this::checkBridgeHealth);
    }

    // ── Strategy Selection → auto-populate from bridge ────────────────

    /**
     * Called whenever the strategy dropdown changes.
     * Fetches /backtest-settings and populates Symbol, Period,
     * Date Range, and Initial Capital from the strategy's actual XML config.
     */
    private void onStrategySelected() {
        String strategy = (String) strategyCombo.getSelectedItem();
        String project = (String) projectCombo.getSelectedItem();
        String databank = (String) databankCombo.getSelectedItem();

        if (strategy == null || strategy.isEmpty()) {
            return; // nothing selected yet
        }

        new Thread(() -> {
            try {
                // Build URL:
                // /backtest-settings?project=...&databank=...&strategy_name=...
                String params = String.format(
                        "project=%s&databank=%s&strategy_name=%s",
                        encode(project),
                        encode(databank),
                        encode(strategy)
                );
                HttpRequest req = HttpRequest.newBuilder()
                        .uri(URI.create(BRIDGE_URL + "/backtest-settings?" + params))
                        .GET()
                        .build();

                HttpResponse<String> resp = client.send(
                        req,
                        HttpResponse.BodyHandlers.ofString()
                );

                String body = resp.body();
                if (resp.statusCode() != 200) {
                    logStatus("Error: HTTP " + resp.statusCode() + " — " + body);
                    return;
                }

                // Parse JSON response manually (no Jackson/Gson dependency)
                String symbol = jsonGetString(body, "symbol");
                String fromDate = jsonGetString(body, "fromDate");
                String toDate = jsonGetString(body, "toDate");
                String timeframe = jsonGetString(body, "timeframe");
                String capital = jsonGetString(body, "initialCapital");

                // Auto-populate fields on EDT
                SwingUtilities.invokeLater(() -> {
                    if (symbol != null && !symbol.isEmpty()) {
                        // Set the symbol combo to the fetched value
                        // Also add it as a suggestion if not already present
                        addToComboBox(symbolCombo, symbol);
                        symbolCombo.setSelectedItem(symbol);
                    }
                    if (timeframe != null && !timeframe.isEmpty()) {
                        addToComboBox(periodCombo, timeframe);
                        periodCombo.setSelectedItem(timeframe);
                    }
                    if (fromDate != null && !fromDate.isEmpty()) {
                        dateFromField.setText(fromDate);
                    }
                    if (toDate != null && !toDate.isEmpty()) {
                        dateToField.setText(toDate);
                    }
                    if (capital != null && !capital.isEmpty()) {
                        initialCapitalField.setText(capital);
                    }
                    logStatus("Settings loaded for: " + strategy);
                });

            } catch (Exception ex) {
                SwingUtilities.invokeLater(() ->
                        logStatus("Error fetching settings: " + ex.getMessage()));
            }
        }).start();
    }

    // ── JSON helper (minimal, no external dependency) ──────────────────

    private static String jsonGetString(String json, String key) {
        Pattern p = Pattern.compile("\"" + Pattern.quote(key) + "\"\\s*:\\s*\"([^\"]*)\"");
        Matcher m = p.matcher(json);
        if (m.find()) {
            return m.group(1);
        }
        // Try numeric value (for initialCapital)
        p = Pattern.compile("\"" + Pattern.quote(key) + "\"\\s*:\\s*([\\d.]+)");
        m = p.matcher(json);
        if (m.find()) {
            return m.group(1);
        }
        return null;
    }

    // ── Combo box helper ──────────────────────────────────────────────

    private void addToComboBox(JComboBox<String> combo, String value) {
        for (int i = 0; i < combo.getItemCount(); i++) {
            if (combo.getItemAt(i).equals(value)) return; // already present
        }
        combo.addItem(value);
    }

    // ── URL encoding ──────────────────────────────────────────────────

    private static String encode(String s) {
        try {
            java.net.URLEncoder.encode(s, "UTF-8");
            return java.net.URLEncoder.encode(s, "UTF-8")
                    .replace("+", "%20")  // spaces
                    .replace("(", "%28")
                    .replace(")", "%29");
        } catch (java.io.UnsupportedEncodingException e) {
            return s;
        }
    }

    // ── Backtest execution ────────────────────────────────────────────

    private void runBacktest(boolean runAll) {
        String strategy = (String) strategyCombo.getSelectedItem();
        String symbol = (String) symbolCombo.getSelectedItem();
        String period = (String) periodCombo.getSelectedItem();
        String dateFrom = dateFromField.getText();
        String dateTo = dateToField.getText();
        String capital = initialCapitalField.getText();

        logStatus("Sending backtest request...");

        new Thread(() -> {
            try {
                String body = String.format(
                        "{\"strategyName\":\"%s\",\"symbol\":\"%s\",\"period\":\"%s\"," +
                        "\"fromDate\":\"%s\",\"toDate\":\"%s\",\"deposit\":\"%s\"}",
                        strategy, symbol, period, dateFrom, dateTo, capital
                );
                byte[] payload = body.getBytes("UTF-8");

                HttpRequest req = HttpRequest.newBuilder()
                        .uri(URI.create(BRIDGE_URL + "/backtest"))
                        .header("Content-Type", "application/json")
                        .POST(HttpRequest.BodyPublishers.ofByteArray(payload))
                        .build();

                HttpResponse<String> resp = client.send(
                        req,
                        HttpResponse.BodyHandlers.ofString()
                );

                if (resp.statusCode() == 200) {
                    logStatus("Backtest submitted: " + resp.body());
                } else {
                    logStatus("Backtest error: HTTP " + resp.statusCode() + " — " + resp.body());
                }
            } catch (Exception ex) {
                SwingUtilities.invokeLater(() ->
                        logStatus("Backtest failed: " + ex.getMessage()));
            }
        }).start();
    }

    // ── Health check ──────────────────────────────────────────────────

    private void checkBridgeHealth() {
        new Thread(() -> {
            try {
                HttpRequest req = HttpRequest.newBuilder()
                        .uri(URI.create(BRIDGE_URL + "/health"))
                        .GET()
                        .build();
                HttpResponse<String> resp = client.send(
                        req,
                        HttpResponse.BodyHandlers.ofString()
                );
                if (resp.statusCode() == 200) {
                    logStatus("Bridge connected: " + resp.body());
                } else {
                    logStatus("Bridge not responding (HTTP " + resp.statusCode() + ")");
                }
            } catch (Exception ex) {
                logStatus("Bridge not running — start sqx-mt5-bridge first");
            }
        }).start();
    }

    // ── Status log ────────────────────────────────────────────────────

    private void logStatus(String msg) {
        System.out.println("[MT5Bridge] " + msg);
    }

    // ── Entry point ──────────────────────────────────────────────────

    public static void main(String[] args) {
        SwingUtilities.invokeLater(() -> new UI().setVisible(true));
    }
}
