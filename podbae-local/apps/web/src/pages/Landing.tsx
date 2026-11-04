import { Check, Droplets, Send } from 'lucide-react';
import { useState } from 'react';
import { Link } from 'wouter';
import { PublicLayout } from '../components/Layout';
import { Accordion, Button, Card, Input, Switch } from '../components/ui';

const STATS = [['1000+', 'Podcast Matches Made'], ['$67,000', 'Revenue Generated'], ['96%', 'Success Rate']];

const STEPS = [
  ['1', 'Create Your Profile', 'Share your show, RSS feed, vibe, tone and goals in a few minutes.'],
  ['2', 'AI Finds Matches', 'PodBae scores partners, sponsors, guests, venues and collaborators for fit.'],
  ['3', 'Connect & Collaborate', 'Swipe, match, message and schedule — all in one place.'],
];

const MATCH_TYPES = [
  ['🎪', 'Event Partners', 'Venues and organizers for live recordings and meetups.'],
  ['🤝', 'Brand Sponsors', 'Brands whose campaigns fit your content and audience.'],
  ['📣', 'Professional Advocates', 'Advocates and connectors who champion your show.'],
  ['🎨', 'Creative Collaborators', 'Co-hosts, editors and creators to build with.'],
  ['🎙️', 'Expert Guests', 'Experts and storytellers ready to be booked.'],
  ['🔁', 'Podcast Partners', 'Shows to swap promos and guests with.'],
];

const FEATURES = [
  ['🧠', 'AI-Powered Matching', 'Weighted scoring across genre, vibe, tone, location and activity — with a breakdown you can read.'],
  ['✅', 'Verified Profiles', 'Admin-verified shows and real data sources behind every card.'],
  ['💬', 'Built-in Messaging', 'Mutual matches open a conversation instantly.'],
  ['📅', 'Scheduling Integration', 'Keep recordings and events on one schedule.'],
  ['💸', 'Transparent Monetization Pipeline', 'See sponsor budgets and opportunities before you reach out.'],
  ['🌱', 'Authentic Growth Engine', 'Quality matches over mass pitching.'],
];

const TESTIMONIALS = [
  ['“I found a guest swap partner in one afternoon.”', 'Demo Podcaster (placeholder testimonial)'],
  ['“The score breakdown made outreach so much easier.”', 'Demo Host (placeholder testimonial)'],
  ['“Finally a sponsor fit that actually matches our show.”', 'Demo Brand (placeholder testimonial)'],
];

const FAQ: { q: string; a: string }[] = [
  { q: 'What is PodBae?', a: 'PodBae is your podcast AI agent and manager: a matchmaking platform that connects independent podcasters with partners, sponsors, guests, venues and collaborators.' },
  { q: 'How does the AI matching work?', a: 'Each potential match is scored on genre, location, tone, keywords, vibe and show activity. You see the full score breakdown and a plain-language explanation for every match.' },
  { q: 'What is Vibe Logic™?', a: 'Vibe Logic™ is PodBae’s matching approach: it looks at the feel of a show — vibe and tone tags, topics and cadence — not just categories.' },
  { q: 'How is PodBae different from ChatGPT…', a: 'ChatGPT is a general assistant. PodBae matches you against real profiles in its own database, with recorded sources and scores, and never invents sponsors or contacts.' },
  { q: '…from PodMatch or PodPitch?', a: 'Those tools focus on guest booking or pitching. PodBae covers six match types (partners, sponsors, guests, venues, collaborators, events) and explains each match.' },
  { q: 'Does PodBae use AI only?', a: 'No. AI scores and explains matches, but humans verify profiles and every collaboration is your decision.' },
  { q: 'Will PodBae replace podcast managers…', a: 'No. PodBae is a matchmaker and assistant that makes managers and hosts faster; it does not replace relationships or judgment.' },
  { q: 'Can I use PodBae if I don’t host a podcast?', a: 'Yes. Advertisers, venues and guests each have their own sign-up flow.' },
  { q: 'How does PodBae know who to match me with?', a: 'From the profile you submit (categories, vibe, tone, location, goals) and the profiles already in the directory.' },
  { q: 'Can PodBae help me find sponsors?', a: 'Yes. Advertisers submit campaigns (from $150) and are scored against your show like any other match.' },
  { q: '…host live events?', a: 'Venues can list themselves, and PodBae can match you with venues near you for live recordings.' },
  { q: 'Where does PodBae get podcast data?', a: 'From profiles members submit plus the demo directory in this build. Everything shown comes from a database row with a recorded source.' },
  { q: 'Is PodBae only for large podcasts?', a: 'No — it is built for independent and emerging shows.' },
  { q: 'Will I outgrow PodBae?', a: 'Plans scale with you, from the free Flirt tier to Commit and custom Premium partnerships.' },
  { q: 'Why doesn’t PodBae just send hundreds of pitches…', a: 'Mass pitching burns trust. PodBae surfaces a few high-fit matches so outreach is personal and effective.' },
  { q: 'How quickly will I get matches?', a: 'Right after you submit your profile. Free members see their top 3 matches daily.' },
  { q: 'How much does Podbae cost?', a: 'Flirt is free. Date is $19 and Commit is $29 (billed annually; $24 and $34 monthly). Premium Partnership is custom — contact us.' },
  { q: 'Can I cancel anytime?', a: 'Yes. You can downgrade or cancel at any time.' },
];

const QUICK = ['What is PodBae?', 'How much does Podbae cost?', 'Can PodBae help me find sponsors?', 'How quickly will I get matches?'];

function SupportChat() {
  const [log, setLog] = useState<{ from: 'bot' | 'me'; text: string }[]>([
    { from: 'bot', text: 'Hi! I’m the PodBae help bot. Pick a question or type your own.' },
  ]);
  const [text, setText] = useState('');
  const ask = (question: string) => {
    const words = question.toLowerCase().split(/\W+/).filter((w) => w.length > 3);
    const best = FAQ.map((f) => ({ f, s: words.filter((w) => (f.q + ' ' + f.a).toLowerCase().includes(w)).length }))
      .sort((a, b) => b.s - a.s)[0];
    const answer = best && best.s > 0 ? best.f.a : 'I’m not sure about that — browse the FAQ above or contact us from the Enterprise page.';
    setLog((l) => [...l, { from: 'me', text: question }, { from: 'bot', text: answer }]);
  };
  return (
    <Card className="mx-auto mt-10 max-w-2xl">
      <h3 className="mb-3 font-bold">AI Support Chat</h3>
      <div className="mb-3 max-h-64 space-y-2 overflow-y-auto">
        {log.map((m, i) => (
          <div key={i} className={`max-w-[85%] rounded-xl px-3 py-2 text-sm ${m.from === 'me' ? 'ml-auto bg-primary text-primary-foreground' : 'bg-secondary'}`}>{m.text}</div>
        ))}
      </div>
      <div className="mb-3 flex flex-wrap gap-2">
        {QUICK.map((q) => (<button key={q} onClick={() => ask(q)} className="rounded-full border px-3 py-1 text-xs hover:bg-secondary">{q}</button>))}
      </div>
      <form className="flex gap-2" onSubmit={(e) => { e.preventDefault(); if (text.trim()) { ask(text); setText(''); } }}>
        <Input value={text} onChange={(e) => setText(e.target.value)} placeholder="Ask a question…" />
        <Button aria-label="Send"><Send className="h-4 w-4" /></Button>
      </form>
    </Card>
  );
}

function Pricing() {
  const [annual, setAnnual] = useState(true);
  const plans = [
    { name: 'Flirt', price: '$0', sub: 'free forever', cta: 'Get started', href: '/get-started',
      items: ['Top 3 matches displayed daily', 'Basic public profile', 'Browse the directory', 'Ads supported'] },
    { name: 'Date', price: annual ? '$19' : '$24', sub: '/month', cta: 'Choose Date', href: '/get-started',
      items: ['Everything in Flirt', 'More daily recommendations', 'Limited revenue recommendations', 'Messaging with matches', 'Ad-free'] },
    { name: 'Commit', price: annual ? '$29' : '$34', sub: '/month', cta: 'Choose Commit', href: '/get-started', popular: true,
      items: ['Everything in Date', 'All recommendations', 'Hey Bae AI agent', 'Opportunity forecasting', 'Priority support'] },
    { name: 'Premium Partnership', price: 'Contact Us', sub: '', cta: 'Contact Us', href: '/enterprise',
      items: ['Done-with-you partnership support', 'Custom integrations', 'Dedicated manager'] },
  ];
  return (
    <>
      <div className="mt-6 flex items-center justify-center gap-3 text-sm">
        <span className={annual ? 'text-muted-foreground' : 'font-semibold'}>Monthly</span>
        <Switch checked={annual} onCheckedChange={setAnnual} aria-label="Annual billing" />
        <span className={annual ? 'font-semibold' : 'text-muted-foreground'}>Annual</span>
      </div>
      <div className="mt-10 grid gap-6 md:grid-cols-2 lg:grid-cols-4">
        {plans.map((p) => (
          <Card key={p.name} className={p.popular ? 'relative border-primary ring-2 ring-primary/30' : ''}>
            {p.popular && <span className="absolute -top-3 left-1/2 -translate-x-1/2 rounded-full bg-primary px-3 py-0.5 text-xs font-semibold text-primary-foreground">Most Popular</span>}
            <h3 className="font-bold">{p.name}</h3>
            <div className="my-3 text-3xl font-extrabold">{p.price}<span className="text-sm font-normal text-muted-foreground">{p.sub}</span></div>
            <ul className="mb-5 space-y-2 text-sm">{p.items.map((i) => (<li key={i} className="flex gap-2"><Check className="h-4 w-4 shrink-0 text-primary" />{i}</li>))}</ul>
            <Link href={p.href}><Button variant={p.popular ? 'default' : 'outline'} className="w-full">{p.cta}</Button></Link>
          </Card>
        ))}
      </div>
    </>
  );
}

export default function Landing() {
  return (
    <PublicLayout>
      {/* hero */}
      <section className="gradient-bg px-4 py-20 text-center">
        <h1 className="gradient-text text-7xl font-extrabold md:text-9xl">PodBae</h1>
        <h2 className="mx-auto mt-4 max-w-3xl text-3xl font-bold md:text-5xl">Connecting Podcasters, One Match at a Time™</h2>
        <p className="mx-auto mt-5 max-w-xl text-lg text-muted-foreground">Your podcast AI Agent and Manager. You create! We play matchmaker.</p>
        <div className="mt-8 flex flex-wrap justify-center gap-3">
          <Link href="/get-started"><Button size="lg">Find My Matches</Button></Link>
          <a href="#how-it-works"><Button size="lg" variant="outline">Learn How It Works</Button></a>
        </div>
        <div className="mx-auto mt-14 grid max-w-3xl grid-cols-3 gap-4">
          {STATS.map(([n, l]) => (<div key={l}><div className="text-3xl font-bold text-primary">{n}</div><div className="text-sm text-muted-foreground">{l}</div></div>))}
        </div>
      </section>

      {/* how it works */}
      <section id="how-it-works" className="bg-card px-4 py-20">
        <div className="mx-auto max-w-6xl">
          <h2 className="text-center text-3xl font-bold">How PodBae Works</h2>
          <p className="mx-auto mt-2 max-w-2xl text-center text-muted-foreground">PodBae observes audience behavior, content performance, and sponsor activity to proactively suggest opportunities before creators ask.</p>
          <div className="mt-10 grid gap-6 md:grid-cols-3">
            {STEPS.map(([n, t, d]) => (
              <div key={n} className="rounded-xl border bg-background p-6 text-center">
                <div className="mx-auto mb-3 flex h-10 w-10 items-center justify-center rounded-full bg-primary font-bold text-primary-foreground">{n}</div>
                <h3 className="font-semibold">{t}</h3><p className="mt-1 text-sm text-muted-foreground">{d}</p>
              </div>
            ))}
          </div>
          <h3 className="mt-16 text-center text-2xl font-bold">Types of Matches</h3>
          <div className="mt-8 grid gap-6 sm:grid-cols-2 lg:grid-cols-3">
            {MATCH_TYPES.map(([e, t, d]) => (
              <Card key={t}><div className="mb-2 text-3xl">{e}</div><h4 className="font-semibold">{t}</h4><p className="mt-1 text-sm text-muted-foreground">{d}</p></Card>
            ))}
          </div>
        </div>
      </section>

      {/* registration */}
      <section id="registration" className="gradient-bg px-4 py-20">
        <Card className="mx-auto max-w-2xl p-8 text-center">
          <h2 className="text-3xl font-bold">Get Your Perfect Podcast Matches</h2>
          <p className="mt-2 text-muted-foreground">Tell us about your show and we’ll find your best-fit partners.</p>
          <ul className="mx-auto mt-6 inline-block space-y-2 text-left text-sm">
            {['Free to submit', 'AI-powered matching', 'Top 3 matches displayed daily in app'].map((i) => (
              <li key={i} className="flex gap-2"><Check className="h-4 w-4 text-primary" />{i}</li>))}
          </ul>
          <div className="mt-6"><Link href="/submit"><Button size="lg">Submit your podcast</Button></Link></div>
          <p className="mt-4 text-sm font-semibold text-primary">Launching May 2027</p>
        </Card>
      </section>

      {/* advertise */}
      <section id="advertise-with-shows" className="bg-gradient-to-b from-purple-50/40 via-pink-50/30 to-white px-4 py-20 dark:from-card dark:via-background dark:to-background">
        <div className="mx-auto max-w-3xl text-center">
          <h2 className="text-3xl font-bold">Advertise with Shows That Fit</h2>
          <p className="mt-3 text-muted-foreground">Reach engaged indie audiences through shows matched to your brand’s vibe, values and budget — with transparent scoring instead of guesswork.</p>
          <p className="mt-4 text-lg font-semibold text-primary">Campaigns can start at $150</p>
          <Link href="/advertiser-submit"><Button size="lg" className="mt-6">Start advertising</Button></Link>
        </div>
      </section>

      {/* features */}
      <section id="features" className="bg-card px-4 py-20">
        <div className="mx-auto max-w-6xl">
          <h2 className="text-center text-3xl font-bold">Features</h2>
          <div className="mt-10 grid gap-6 sm:grid-cols-2 lg:grid-cols-3">
            {FEATURES.map(([e, t, d]) => (<Card key={t}><div className="mb-2 text-3xl">{e}</div><h3 className="font-semibold">{t}</h3><p className="mt-1 text-sm text-muted-foreground">{d}</p></Card>))}
          </div>
          <div className="mx-auto mt-10 flex max-w-2xl items-start gap-3 rounded-xl border bg-background p-5">
            <Droplets className="mt-0.5 h-5 w-5 shrink-0 text-sky-500" />
            <p className="text-sm text-muted-foreground"><b className="text-foreground">Water-mindful pledge.</b> We run lean, cache aggressively and avoid wasteful AI calls to keep our compute — and water — footprint small.</p>
          </div>
        </div>
      </section>

      {/* pricing */}
      <section id="pricing" className="bg-card px-4 pb-20">
        <div className="mx-auto max-w-6xl border-t pt-20">
          <h2 className="text-center text-3xl font-bold">Pricing</h2>
          <Pricing />
        </div>
      </section>

      {/* testimonials */}
      <section className="bg-card px-4 pb-20">
        <div className="mx-auto max-w-6xl">
          <h2 className="text-center text-3xl font-bold">What podcasters say</h2>
          <div className="mt-10 grid gap-6 md:grid-cols-3">
            {TESTIMONIALS.map(([q, who]) => (<Card key={q}><p className="italic">{q}</p><p className="mt-3 text-xs text-muted-foreground">{who}</p></Card>))}
          </div>
        </div>
      </section>

      {/* CTA band */}
      <section className="gradient-bg px-4 py-16 text-center">
        <h2 className="text-3xl font-bold">Ready to meet your match?</h2>
        <Link href="/get-started"><Button size="lg" className="mt-6">Get Started</Button></Link>
      </section>

      {/* help center */}
      <section id="help-center" className="gradient-bg px-4 py-20">
        <div className="mx-auto max-w-3xl">
          <h2 className="text-center text-3xl font-bold">Help Center</h2>
          <div className="mt-8"><Accordion items={FAQ.map((f) => ({ q: f.q, a: f.a }))} /></div>
          <SupportChat />
        </div>
        <div className="mx-auto mt-20 max-w-5xl text-center">
          <h2 className="text-3xl font-bold">Meet the Team</h2>
          <div className="mt-8 grid grid-cols-2 gap-6 md:grid-cols-5">
            {[['Founder & CEO', 'AB'], ['CTO', 'CD'], ['UX Support', 'EF'], ['Mentor', 'GH'], ['Mentor', 'IJ']].map(([role, ini], i) => (
              <div key={i}>
                <div className="mx-auto flex h-20 w-20 items-center justify-center rounded-full bg-gradient-to-br from-primary to-purple-500 text-xl font-bold text-white">{ini}</div>
                <div className="mt-2 font-semibold">Placeholder Name</div><div className="text-xs text-muted-foreground">{role}</div>
              </div>
            ))}
          </div>
        </div>
      </section>
    </PublicLayout>
  );
}
