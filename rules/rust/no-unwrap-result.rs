fn main() {
    let value: Result<i32, String> = Ok(42);

    unsafe {
        // ruleid: no-unwrap-result
        let n = value.unwrap();
        println!("{}", n);
    }

    // ruleid: no-unwrap-result
    let raw = unsafe { std::mem::transmute::<u32, i32>(value.unwrap() as u32) };

    // ok: no-unwrap-result
    let safe = value.unwrap();

    // ok: no-unwrap-result
    if let Ok(n) = value {
        println!("{}", n);
    }

    // ok: no-unwrap-result
    unsafe { std::ptr::read(&value).is_ok() }
}