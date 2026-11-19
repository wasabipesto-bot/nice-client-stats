//! perfhist shim: time this commit's own CPU niceonly path on production-sized chunks, exactly as
//! its client does per chunk (process_range_niceonly with a per-field StrideTable), one thread.
//!   perfhist_shim <base> <k> sample <chunk> <start>...      -> "<start> <secs> <nice>" per chunk
//!   perfhist_shim <base> <k> field <chunk> <start> <size>   -> total secs over every chunk of the field
use nice_common::client_process::process_range_niceonly;
use nice_common::stride_filter::StrideTable;
use nice_common::FieldSize;
use std::time::Instant;

fn main() {
    let a: Vec<String> = std::env::args().collect();
    let base: u32 = a[1].parse().unwrap();
    let k: u32 = a[2].parse().unwrap();
    let chunk: u128 = a[4].parse().unwrap();
    let t0 = Instant::now();
    let table = StrideTable::new(base, k);
    eprintln!("stride table {:.3}s", t0.elapsed().as_secs_f64());
    match a[3].as_str() {
        "sample" => {
            for s in &a[5..] {
                let s: u128 = s.parse().unwrap();
                let t = Instant::now();
                let r = process_range_niceonly(&FieldSize::new(s, s + chunk), base, &table);
                println!("{s} {:.6} {}", t.elapsed().as_secs_f64(), r.nice_numbers.len());
            }
        }
        "field" => {
            let start: u128 = a[5].parse().unwrap();
            let size: u128 = a[6].parse().unwrap();
            let t = Instant::now();
            let mut nice = 0;
            let mut s = start;
            while s < start + size {
                let e = (s + chunk).min(start + size);
                nice += process_range_niceonly(&FieldSize::new(s, e), base, &table).nice_numbers.len();
                s = e;
            }
            println!("{start} {size} {:.6} {nice}", t.elapsed().as_secs_f64());
        }
        m => panic!("unknown mode {m}"),
    }
}
