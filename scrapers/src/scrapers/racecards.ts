export async function fetchRacecard(date: string) {
  const url = `https://www.sportinglife.com/api/horse-racing/racing/racecards/${date}`;

  const response = await fetch(url, {
    headers: {
      Accept: "application/json",
      "User-Agent": "data-jockey/0.1"
    }
  });

  if (!response.ok) {
    throw new Error(`Request failed: ${response.status}`);
  }

  return response.json();
}