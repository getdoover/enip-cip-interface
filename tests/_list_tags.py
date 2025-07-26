#!/usr/bin/env python3
"""
Simple EtherNet/IP Tag Discovery Tool
Lists all available tags from an EtherNet/IP server
"""

import logging
import sys
from pylogix import PLC


def discover_tags(plc_host: str = '127.0.0.1', all_tags: bool = True) -> list:
    """
    Discover all available tags from the EtherNet/IP server.
    
    Args:
        plc_host: The IP address of the EtherNet/IP server
        all_tags: If True, get controller and program tags. If False, only controller tags.
        
    Returns:
        List of available tag names
    """
    discovered_tags = []
    
    try:
        with PLC() as comm:
            comm.IPAddress = plc_host
            
            print(f"Discovering tags from {plc_host}...")
            
            # Get tag list
            result = comm.GetTagList(allTags=all_tags)
            
            if result.Status == "Success" and result.Value is not None:
                # The Value should contain the list of tags
                if isinstance(result.Value, list):
                    discovered_tags = result.Value
                elif isinstance(result.Value, dict):
                    # Sometimes it might be returned as a dict
                    discovered_tags = list(result.Value.keys())
                else:
                    print(f"Unexpected tag list format: {type(result.Value)}")
                    print(f"Tag list content: {result.Value}")
            else:
                print(f"Failed to get tag list: {result.Status}")
                
    except Exception as e:
        print(f"Error discovering tags: {e}")
    
    return discovered_tags


def main():
    """Main function to list all available tags"""
    
    # Get command line arguments
    plc_host = '127.0.0.1'
    all_tags = True
    
    if len(sys.argv) > 1:
        plc_host = sys.argv[1]
    
    if len(sys.argv) > 2:
        all_tags = sys.argv[2].lower() in ['true', '1', 'yes', 'all']
    
    print(f"EtherNet/IP Tag Discovery Tool")
    print(f"Target: {plc_host}")
    print(f"All tags: {all_tags}")
    print("-" * 50)
    
    # Discover tags
    tags = discover_tags(plc_host, all_tags)
    
    if tags:
        print(f"\nFound {len(tags)} tags:")
        print("-" * 30)
        for i, tag in enumerate(tags, 1):
            print(f"{i:3d}. {tag}")
    else:
        print("\nNo tags found or discovery failed.")
        print("\nPossible reasons:")
        print("- EtherNet/IP server is not running")
        print("- Wrong IP address")
        print("- Network connectivity issues")
        print("- Server doesn't support tag discovery")


if __name__ == "__main__":
    main() 