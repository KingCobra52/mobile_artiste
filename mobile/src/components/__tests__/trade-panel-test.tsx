import { fireEvent, render, waitFor } from '@testing-library/react-native';

import { TradePanel } from '@/components/trade-panel';
import { buyShares, sellShares } from '@/lib/api';
import { useAuth } from '@/lib/auth-context';

jest.mock('@/lib/api', () => ({
  buyShares: jest.fn(),
  sellShares: jest.fn(),
}));

jest.mock('@/lib/auth-context', () => ({ useAuth: jest.fn() }));

jest.mock('@/hooks/use-theme', () => ({
  useTheme: () => ({ text: '#111', textSecondary: '#666', background: '#fff' }),
}));

const mockedUseAuth = jest.mocked(useAuth);
const mockedBuyShares = jest.mocked(buyShares);
const mockedSellShares = jest.mocked(sellShares);

beforeEach(() => {
  mockedUseAuth.mockReturnValue({ session: { access_token: 'access-token' } as never, loading: false });
  mockedBuyShares.mockReset();
  mockedSellShares.mockReset();
});

describe('<TradePanel />', () => {
  const props = {
    artistId: 7,
    pricePerShare: 125,
    sharesOwned: 3,
    onTraded: jest.fn(),
  };

  it('shows a sign-in prompt for anonymous visitors', () => {
    mockedUseAuth.mockReturnValue({ session: null, loading: false });

    const screen = render(<TradePanel {...props} />);

    expect(screen.getByText('Sign in on the Account tab to trade this artist.')).toBeOnTheScreen();
  });

  it('validates quantities before sending a trade', () => {
    const screen = render(<TradePanel {...props} />);
    fireEvent.changeText(screen.getByLabelText('Number of shares'), '0');
    fireEvent.press(screen.getByLabelText('Buy'));

    expect(screen.getByText('Enter a whole number of shares greater than zero.')).toBeOnTheScreen();
    expect(mockedBuyShares).not.toHaveBeenCalled();
  });

  it('submits a buy and reports the updated balance and position', async () => {
    mockedBuyShares.mockResolvedValue({
      bars: '9750.00',
      shares_owned: 5,
      price_per_share: 125,
      total: 250,
    });
    const onTraded = jest.fn();
    const screen = render(<TradePanel {...props} onTraded={onTraded} />);

    fireEvent.changeText(screen.getByLabelText('Number of shares'), '2');
    fireEvent.press(screen.getByLabelText('Buy'));

    await waitFor(() => expect(mockedBuyShares).toHaveBeenCalledWith('access-token', 7, 2));
    expect(onTraded).toHaveBeenCalledTimes(1);
    expect(screen.getByText('Done. 9,750 bars left, 5 owned.')).toBeOnTheScreen();
  });

  it('renders the rejection returned by a sell request', async () => {
    mockedSellShares.mockRejectedValue(new Error('Invalid number of shares to sell'));
    const screen = render(<TradePanel {...props} />);

    fireEvent.press(screen.getByLabelText('Sell'));

    expect(await screen.findByText('Invalid number of shares to sell')).toBeOnTheScreen();
  });
});
