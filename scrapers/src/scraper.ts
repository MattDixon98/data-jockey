import * as cheerio from "cheerio";

export type ScrapeResult = {
  title: string | null;
  metaDescription: string | null;
  canonicalUrl: string | null;
};

export async function scrapePage(url: string): Promise<ScrapeResult> {
  const response = await fetch(url);

  if (!response.ok) {
    throw new Error(`Fetch failed with status ${response.status}`);
  }

  const html = await response.text();
  const $ = cheerio.load(html);

  return {
    title: $("title").first().text() || null,
    metaDescription: $('meta[name="description"]').attr("content") || null,
    canonicalUrl: $('link[rel="canonical"]').attr("href") || null,
  };
}
