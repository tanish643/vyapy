import subprocess
import threading
import sys
import os
import shutil
import time
from pathlib import Path

# --- Configuration ---
# Update these values before running the script on your Mac
WORKSPACE = "YourApp.xcworkspace"  # Or use PROJECT = "YourApp.xcodeproj"
SCHEME = "YourAppScheme"

# Simulator UDIDs (from `xcrun simctl list devices`)
DEVICE_A_UDID = "A8C31FA6-AE36-41E8-897A-F628B15A980D"  # iPhone 16 Pro Simulator (Consumer)
DEVICE_B_UDID = "F7661759-D7EE-4A7E-9357-0EF0CCE03DEF"  # iPad Air 11-inch M3 Simulator (Business)

# Output paths
BASE_OUT_DIR = Path("/tmp/vyapy_xctest")

class XCTestAgent:
    def __init__(self, name, udid, output_dir):
        self.name = name
        self.udid = udid
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)

        # Unique paths for isolation
        self.derived_data_path = self.output_dir / "DerivedData"
        self.result_bundle_path = self.output_dir / f"{name}_Results.xcresult"
        self.log_file = self.output_dir / f"{name}_xcodebuild.log"

        # Clean old results if they exist to prevent xcodebuild errors
        if self.result_bundle_path.exists():
            shutil.rmtree(self.result_bundle_path)

        # Boot simulator if not already running
        self._boot_simulator()

    def _boot_simulator(self):
        """Boot the simulator if it's not already running."""
        try:
            result = subprocess.run(
                ["xcrun", "simctl", "bootstatus", self.udid, "-b"],
                capture_output=True, text=True, timeout=60
            )
            if result.returncode == 0:
                print(f"[{self.name}] Simulator {self.udid} is booted and ready.")
            else:
                print(f"[{self.name}] Failed to boot simulator: {result.stderr}")
        except subprocess.TimeoutExpired:
            print(f"[{self.name}] Simulator boot timed out.")
        except Exception as e:
            print(f"[{self.name}] Simulator boot error: {e}")
            
    def run_tests(self, xctestrun_path, extra_args=None):
        """Runs test-without-building using the compiled .xctestrun file."""
        print(f"[{self.name}] Starting tests on device: {self.udid}")
        
        cmd = [
            "xcodebuild",
            "test-without-building",
            "-destination", f"id={self.udid}",
            "-xctestrun", str(xctestrun_path),
            "-derivedDataPath", str(self.derived_data_path),
            "-resultBundlePath", str(self.result_bundle_path)
        ]
        
        if extra_args:
             cmd.extend(extra_args)
        
        print(f"[{self.name}] Logs saving to: {self.log_file}")
        
        with open(self.log_file, "w") as log:
            # Popen allows us to run this asynchronously without blocking the main Python thread
            process = subprocess.Popen(
                cmd, 
                stdout=log, 
                stderr=subprocess.STDOUT, 
                text=True
            )
            process.wait()

        if process.returncode == 0:
            print(f"[{self.name}] ✅ Tests PASSED! Results: {self.result_bundle_path}")
        else:
            print(f"[{self.name}] ❌ Tests FAILED (Exit Code {process.returncode}). Check logs: {self.log_file}")

def build_for_testing(workspace, scheme, derived_data_path):
    """Compiles the app and tests ONCE and generates the .xctestrun file."""
    print("🚀 Step 1: Building app and tests (build-for-testing)...")
    
    cmd = [
        "xcodebuild",
        "build-for-testing",
        "-workspace", workspace,
        "-scheme", scheme,
        "-destination", "generic/platform=iOS Simulator",
        "-derivedDataPath", str(derived_data_path)
    ]
    
    # Run the build synchronously
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        print("❌ Build failed!")
        print(result.stdout[-2000:]) # Print last 2000 chars of output
        print(result.stderr)
        sys.exit(1)
        
    print("✅ Build successful!")
    
    # Locate the generated .xctestrun file
    # It usually lives in DerivedData/Build/Products/
    build_products_dir = Path(derived_data_path) / "Build" / "Products"
    xctestrun_files = list(build_products_dir.glob("*.xctestrun"))
    
    if not xctestrun_files:
        print(f"❌ Error: Could not find .xctestrun file in {build_products_dir}")
        sys.exit(1)
        
    xctestrun_path = xctestrun_files[0]
    print(f"📄 Found test run file: {xctestrun_path}")
    return xctestrun_path

def main():
    print("=" * 60)
    print("  Vyapy - Parallel Native XCTest Runner")
    print("=" * 60)
    
    # Shared DerivedData for the initial build to avoid duplicate compilation
    shared_build_dir = BASE_OUT_DIR / "SharedBuild"
    
    # 1. Build the app and tests once
    xctestrun_path = build_for_testing(WORKSPACE, SCHEME, shared_build_dir)
    
    # 2. Setup the parallel agents
    agent_a = XCTestAgent("Consumer", DEVICE_A_UDID, BASE_OUT_DIR / "Consumer_Agent")
    agent_b = XCTestAgent("Business", DEVICE_B_UDID, BASE_OUT_DIR / "Business_Agent")
    
    # 3. Define the test execution functions for the threads
    # You can pass -only-testing:TestBundle/TestSuite/TestCase to run specific segments
    def run_agent_a():
        agent_a.run_tests(xctestrun_path, extra_args=["-only-testing:VyapyTests/ConsumerScenarios"])
        
    def run_agent_b():
        agent_b.run_tests(xctestrun_path, extra_args=["-only-testing:VyapyTests/BusinessScenarios"])
        
    print("\n🚀 Step 2: Launching tests concurrently on both simulators...")
    start_time = time.time()
    
    # Start threads
    thread_a = threading.Thread(target=run_agent_a)
    thread_b = threading.Thread(target=run_agent_b)
    
    thread_a.start()
    thread_b.start()
    
    # Wait for both to finish
    thread_a.join()
    thread_b.join()
    
    duration = time.time() - start_time
    print(f"\n🎉 All tests completed in {duration:.2f} seconds!")
    print(f"📊 Results available at:\n  - {agent_a.result_bundle_path}\n  - {agent_b.result_bundle_path}")

if __name__ == "__main__":
    main()
