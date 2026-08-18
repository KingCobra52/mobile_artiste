import { buyShares, fetchMarket } from '@/lib/api';

const fetchMock = jest.fn();

beforeEach(() => {
  fetchMock.mockReset();
  Object.assign(globalThis, { fetch: fetchMock });
});

describe('API client', () => {
  it('requests the public market without authentication', async () => {
    const market = [{ id: 4, name: 'Mitski', price_per_share: 12.5 }];
    fetchMock.mockResolvedValue({ ok: true, json: async () => market });

    await expect(fetchMarket()).resolves.toEqual(market);
    expect(fetchMock).toHaveBeenCalledWith('http://localhost:8000/market', {
      method: 'GET',
      headers: {},
      body: undefined,
      signal: expect.any(AbortSignal),
    });
  });

  it('sends authenticated buy orders as JSON', async () => {
    const result = { bars: '9750.00', shares_owned: 2, price_per_share: 125, total: 250 };
    fetchMock.mockResolvedValue({ ok: true, json: async () => result });

    await expect(buyShares('access-token', 7, 2)).resolves.toEqual(result);
    expect(fetchMock).toHaveBeenCalledWith('http://localhost:8000/buy', {
      method: 'POST',
      headers: {
        Authorization: 'Bearer access-token',
        'Content-Type': 'application/json',
      },
      body: JSON.stringify({ artist_id: 7, shares: 2 }),
      signal: expect.any(AbortSignal),
    });
  });

  it('surfaces the API trade-rejection message', async () => {
    fetchMock.mockResolvedValue({
      ok: false,
      status: 400,
      json: async () => ({ detail: 'Not a sufficient amount of bars' }),
    });

    await expect(buyShares('access-token', 7, 2)).rejects.toThrow(
      'Not a sufficient amount of bars'
    );
  });

  it('explains a connection failure', async () => {
    fetchMock.mockRejectedValue(new TypeError('Network request failed'));

    await expect(fetchMarket()).rejects.toThrow(
      "Can't reach the API at http://localhost:8000. Is it running?"
    );
  });
});
