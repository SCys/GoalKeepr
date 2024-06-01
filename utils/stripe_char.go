package main

import (
	"bufio"
	"fmt"
	"os"
	"strings"
)

func convertPunctuation(input string) string {
	punctuationMap := map[rune]rune{
		'。': '.',  // 句号
		'，': ',',  // 逗号
		'、': ',',  // 分号
		'；': ';',  // 分号
		'：': ':',  // 冒号
		'！': '!',  // 感叹号
		'？': '?',  // 问号
		'）': ')',  // 右括号
		'（': '(',  // 左括号
		'】': ']',  // 右方括号
		'【': '[',  // 左方括号
		'“': '"',  // 双引号
		'”': '"',  // 双引号
		'‘': '\'', // 单引号
		'’': '\'', // 单引号
	}

	output := []rune{}
	for _, r := range input {
		if replacement, ok := punctuationMap[r]; ok {
			output = append(output, replacement)
		} else {
			output = append(output, r)
		}
	}
	return string(output)
}

func main() {
	if len(os.Args) < 2 {
		fmt.Println("Usage: stripe_char <input_file>")
		return
	}

	inputFile := os.Args[1]
	outputFile := strings.TrimSuffix(inputFile, ".txt") + "_converted.txt"

	file, err := os.Open(inputFile)
	if err != nil {
		fmt.Printf("Error opening file: %v\n", err)
		return
	}
	defer file.Close()

	outFile, err := os.Create(outputFile)
	if err != nil {
		fmt.Printf("Error creating output file: %v\n", err)
		return
	}
	defer outFile.Close()

	scanner := bufio.NewScanner(file)
	writer := bufio.NewWriter(outFile)
	for scanner.Scan() {
		line := scanner.Text()
		convertedLine := convertPunctuation(line)
		_, err := writer.WriteString(convertedLine + "\n")
		if err != nil {
			fmt.Printf("Error writing to output file: %v\n", err)
			return
		}
	}

	if err := scanner.Err(); err != nil {
		fmt.Printf("Error reading from input file: %v\n", err)
		return
	}

	err = writer.Flush()
	if err != nil {
		fmt.Printf("Error flushing output buffer: %v\n", err)
		return
	}

	fmt.Printf("Conversion complete. Output written to %s\n", outputFile)
}
