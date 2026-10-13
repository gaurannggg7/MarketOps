import { AllCommunityModule, ModuleRegistry, themeQuartz } from "ag-grid-community";

// AG Grid Community only: no Enterprise modules or license keys.
ModuleRegistry.registerModules([AllCommunityModule]);

export const gridTheme = themeQuartz.withParams({
  fontSize: 12,
  headerFontSize: 12,
  spacing: 5,
  rowHeight: 30,
  headerHeight: 32,
  accentColor: "#0f766e",
  borderColor: "#e2e8f0",
  headerBackgroundColor: "#f8fafc",
});
