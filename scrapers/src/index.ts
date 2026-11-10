import { scrapePage } from "./scraper.js";

const targetUrl = process.env.TARGET_URL || "https://example.com";

try {
  const result = await scrapePage(targetUrl);
  console.log("Scrape result:", result);
} catch (error) {
  console.error("Scraping failed:", error);
  process.exit(1);
}
