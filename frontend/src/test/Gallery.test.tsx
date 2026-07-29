import { describe, it, expect, vi } from 'vitest';
import { render, screen } from '@testing-library/react';
import React from 'react';
import { Gallery } from '../components/Gallery';

describe('Gallery Component', () => {
  it('renders gallery title and empty state when no media items exist', async () => {
    global.fetch = vi.fn().mockResolvedValue({
      ok: true,
      json: async () => ({ status: 'success', media: [] })
    } as Response);

    render(<Gallery token="mock-jwt-token" refreshTrigger={0} />);

    expect(await screen.findByText('Extracted Media Library')).toBeDefined();
    expect(await screen.findByText('No media downloaded yet')).toBeDefined();
  });
});
