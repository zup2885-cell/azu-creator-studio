// Adapted from dashboard/components/ui/card.tsx in the MIT-licensed upstream.
// Original source and license remain in the parent checkout; see ADAPTATION.md.
import React from 'react';
export function Card({className='',children,...props}) {return <section data-slot="card" className={`card ${className}`} {...props}>{children}</section>}
export function CardHeader({className='',children,...props}) {return <div data-slot="card-header" className={`card-header ${className}`} {...props}>{children}</div>}
export function CardContent({className='',children,...props}) {return <div data-slot="card-content" className={className} {...props}>{children}</div>}
